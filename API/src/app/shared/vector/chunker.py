"""Token-aware text chunker for knowledge-base ingest.

Splits text into overlapping chunks of ~``target_tokens`` tokens.
Uses ``tiktoken`` with the ``cl100k_base`` encoder (OpenAI GPT-4
family — matches the embedding model in v1, ``text-embedding-3-small``)
so token counts are exact rather than character-length approximations.

Splitting strategy (soft boundaries first):

  1. Try paragraph boundaries (``\\n\\n``).
  2. Fall back to sentence boundaries (``.``, ``!``, ``?`` followed
     by whitespace).
  3. Fall back to word boundaries (whitespace).
  4. As a last resort, hard-slice inside a word (only triggers on
     pathological input where a single token exceeds
     ``target_tokens``).

Overlap is measured in tokens too — the last ``overlap_tokens``
tokens of chunk N become the first ``overlap_tokens`` tokens of
chunk N+1 so retrieval doesn't lose an answer that straddles a
split boundary.

Prompt-injection defence: known instruction-hijack markers
(``</context>``, ``<context>``, ``</system>``, ``<system>``,
``SYSTEM:``, ``ASSISTANT:``) are stripped BEFORE chunking. Step 9's
retrieval passes chunks through a structured JSON envelope so this
is belt+braces, but stripping at ingest keeps the corpus itself
clean of markers a future retrieval envelope change might still
respect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ``tiktoken`` cold-loads its BPE files on first call; the module-
# level get_encoding() is intentional so the load happens once per
# worker process, not once per chunk_text() call.
import tiktoken

_ENCODER: Any = tiktoken.get_encoding("cl100k_base")

# Case-insensitive strip list — every marker collapses to a single
# space so an inline "See SYSTEM: hint below" turns into "See  hint
# below" rather than joining unrelated words.
_INJECTION_MARKERS = re.compile(
    r"(?i)</?\s*context\s*>"
    r"|</?\s*system\s*>"
    r"|SYSTEM:"
    r"|ASSISTANT:"
    r"|</?\s*instructions?\s*>",
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One output chunk. ``index`` is 0-based position within the
    input; callers store it on ``tbl_ai_assistant_chunks.chunk_index``
    so re-ingest can idempotently update the same rows."""

    text: str
    index: int
    token_count: int


def _strip_injection_markers(text: str) -> str:
    """Replace every prompt-injection marker with a single space
    (not empty) so surrounding words don't accidentally join."""
    return _INJECTION_MARKERS.sub(" ", text)


def _token_count(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines (paragraph boundary)."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Naive sentence split — . ! ? followed by whitespace/end.
    Good enough for the chunker: we only sentence-split when a
    paragraph itself blew past ``target_tokens``, so the misses are
    already in bad-input territory."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _split_words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text) if w]


def _hard_slice_tokens(text: str, target_tokens: int) -> list[str]:
    """Last-resort: slice a single oversized word into fixed-token
    fragments. Never wanted in practice; the chunker only reaches
    this branch on pathological input like a base64 blob."""
    ids = _ENCODER.encode(text)
    return [_ENCODER.decode(ids[i : i + target_tokens]) for i in range(0, len(ids), target_tokens)]


def _add_with_overlap(chunks: list[str], candidate: str, target_tokens: int) -> None:
    """Append ``candidate`` to ``chunks``, merging with the previous
    chunk when the merge stays under ``target_tokens``. Callers pack
    small paragraphs together this way."""
    if not chunks:
        chunks.append(candidate)
        return
    joined = chunks[-1] + "\n\n" + candidate
    if _token_count(joined) <= target_tokens:
        chunks[-1] = joined
    else:
        chunks.append(candidate)


def _atomic_pieces(text: str, target_tokens: int) -> list[str]:
    """Break ``text`` down until every returned piece is ≤ target.

    Walks paragraph → sentence → word → hard-slice in order,
    combining small siblings via :func:`_add_with_overlap` so we
    don't emit a hundred one-word chunks when the input is a very
    short paragraph followed by a very long one.
    """
    result: list[str] = []
    for para in _split_paragraphs(text) or [text]:
        if _token_count(para) <= target_tokens:
            _add_with_overlap(result, para, target_tokens)
            continue
        # Paragraph too big — try sentences.
        buffer: list[str] = []
        buffer_tokens = 0
        for sent in _split_sentences(para):
            st = _token_count(sent)
            if st > target_tokens:
                # Flush buffer first, then split this sentence by
                # words, then by hard-slice as last resort.
                if buffer:
                    result.append(" ".join(buffer))
                    buffer, buffer_tokens = [], 0
                word_buf: list[str] = []
                word_tokens = 0
                for word in _split_words(sent):
                    wt = _token_count(word)
                    if wt > target_tokens:
                        if word_buf:
                            result.append(" ".join(word_buf))
                            word_buf, word_tokens = [], 0
                        result.extend(_hard_slice_tokens(word, target_tokens))
                        continue
                    if word_tokens + wt > target_tokens:
                        result.append(" ".join(word_buf))
                        word_buf, word_tokens = [word], wt
                    else:
                        word_buf.append(word)
                        word_tokens += wt
                if word_buf:
                    result.append(" ".join(word_buf))
                continue
            if buffer_tokens + st > target_tokens:
                result.append(" ".join(buffer))
                buffer, buffer_tokens = [sent], st
            else:
                buffer.append(sent)
                buffer_tokens += st
        if buffer:
            result.append(" ".join(buffer))
    return result


def chunk_text(
    text: str,
    *,
    target_tokens: int = 800,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    """Return a list of overlapping :class:`Chunk` for ``text``.

    Empty / whitespace-only input returns ``[]`` — Step 10's ingest
    treats this as ``status='failed_no_text'`` so a scanned-image PDF
    doesn't silently produce zero chunks with no error.
    """
    if target_tokens < 1:
        raise ValueError("target_tokens must be >= 1")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be in [0, target_tokens)")

    cleaned = _strip_injection_markers(text)
    if not cleaned.strip():
        return []

    pieces = _atomic_pieces(cleaned, target_tokens)
    if not pieces:
        return []

    # Apply overlap: prepend the tail of the previous chunk to each
    # subsequent chunk, measured in tokens.
    out: list[Chunk] = []
    prev_ids: list[int] = []
    for i, piece in enumerate(pieces):
        if i == 0 or overlap_tokens == 0:
            body = piece
        else:
            overlap_prefix = _ENCODER.decode(prev_ids[-overlap_tokens:])
            body = overlap_prefix + "\n\n" + piece
        body_ids = _ENCODER.encode(body)
        out.append(Chunk(text=body, index=i, token_count=len(body_ids)))
        prev_ids = _ENCODER.encode(piece)
    return out


__all__ = ["Chunk", "chunk_text"]
