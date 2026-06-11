"""Pure threading helpers for inbound email.

Three operations:

  - `extract_message_id(headers)` — pull the `Message-ID` value
    (RFC 5322 angle-bracketed form) out of a header dict. Returns
    the bare id (no brackets) so DB columns + comparisons are
    bracket-agnostic. Tolerates the various ways MUAs case the
    header key (`Message-ID`, `Message-Id`, `message-id`).

  - `extract_thread_keys(headers)` — collect every prior-message id
    we can use to find an existing conversation. The result set
    includes the values of `In-Reply-To` AND every id in the
    `References` chain. Empty when the message has no threading
    headers at all (a brand-new thread).

  - `normalize_subject(subject)` — strip every `Re:` / `Fwd:` /
    `Aw:` (German) / `Antwoord:` / `Sv:` / `Re[2]:` style prefix so
    `Re: Re: Quote for sofa` and `Quote for sofa` collide for the
    subject-based fallback threading rule.

Threading rules the adapter applies (in order):
  1. Any `Message-ID` in `extract_thread_keys` matches a known
     prior `messages.channel_message_id` → same conversation.
  2. Normalized subject + contact matches an OPEN conversation in
     the last 30 days → same conversation.
  3. Else → new conversation.

Everything in this module is pure (no I/O). Tests drive it directly.
"""
from __future__ import annotations

import re
from typing import Iterable


_MESSAGE_ID_KEYS = {"message-id", "message_id"}
_IN_REPLY_TO_KEYS = {"in-reply-to", "in_reply_to"}
_REFERENCES_KEYS = {"references"}


# `Re:` / `Fwd:` / `Aw:` / `Antw:` / `Sv:` / `R:` / `Re[2]:` style
# prefixes. Case-insensitive. Iterates: strips repeatedly so
# `Re: Re: Re: thing` collapses to `thing`.
_REPLY_PREFIX_RE = re.compile(
    r"""
    ^
    \s*
    (?:
        re             # standard
      | re\s*\[\d+\]   # outlook RE[2]: numbering
      | re\s*\(\d+\)   # alt numbering
      | fw             # Fwd / FW
      | fwd
      | aw             # German Re:
      | antwoord       # Dutch Re:
      | antw
      | sv             # Scandinavian Re:
      | wg             # German Fwd:
      | r              # short Russian re:
    )
    \s*:
    """,
    re.IGNORECASE | re.VERBOSE,
)

# RFC 5322 `Message-ID` is `<local@domain>`; some servers embed
# whitespace and brackets in references. This regex is used to
# split `References:` values into individual ids — captures angled
# tokens (`<x@y>`) and tolerates whitespace.
_REFERENCE_TOKEN_RE = re.compile(r"<\s*([^<>\s]+)\s*>")


def _lookup_header(headers: dict, candidates: Iterable[str]) -> str:
    """Case-insensitive header lookup. Returns the FIRST non-empty
    match across `candidates` or empty string.

    We accept headers dicts that have either canonical lower-case
    keys (the shape Gmail's adapter produces) or RFC-style mixed
    case (Microsoft's adapter also produces lower-case after the
    normalisation step). This double-key defence keeps us safe if
    a future adapter forgets to lowercase."""
    if not headers:
        return ""
    # Lowercase view of the dict.
    lowered = {str(k).lower(): v for k, v in headers.items()}
    for key in candidates:
        v = lowered.get(key)
        if v:
            return str(v).strip()
    return ""


def _strip_angle_brackets(raw: str) -> str:
    """`<x@y.com>` → `x@y.com`. Tolerates already-stripped input."""
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        return raw[1:-1].strip()
    return raw


def extract_message_id(headers: dict) -> str:
    """Return the bare Message-ID (no angle brackets). Empty string
    when the header is absent — never raises."""
    raw = _lookup_header(headers, _MESSAGE_ID_KEYS)
    if not raw:
        return ""
    return _strip_angle_brackets(raw)


def extract_thread_keys(headers: dict) -> set[str]:
    """Every prior message id we can hash to find an existing thread.

    Combines:
      - The bare value of `In-Reply-To`.
      - Every angle-bracket token in `References` (space-separated
        chain of `<id1> <id2> <id3>` in arrival order).

    Returns a set of bare ids (no brackets). Empty set means the
    inbound message has no threading info — caller falls back to
    subject matching."""
    keys: set[str] = set()

    in_reply_to = _lookup_header(headers, _IN_REPLY_TO_KEYS)
    if in_reply_to:
        keys.add(_strip_angle_brackets(in_reply_to))

    references = _lookup_header(headers, _REFERENCES_KEYS)
    if references:
        for match in _REFERENCE_TOKEN_RE.finditer(references):
            keys.add(match.group(1).strip())

    keys.discard("")
    return keys


def normalize_subject(subject: str) -> str:
    """Strip reply / forward prefixes repeatedly until the remaining
    subject is stable. Lowercased + trimmed for comparison.

    Returns empty string for None / blank input."""
    if not subject:
        return ""
    cleaned = subject.strip()
    while True:
        new = _REPLY_PREFIX_RE.sub("", cleaned).strip()
        if new == cleaned:
            break
        cleaned = new
    return cleaned.lower()


def subject_thread_key(subject: str) -> str:
    """Stable hash-key for the subject-based threading fallback.
    Currently just `normalize_subject` — kept as a separate name so
    a future signature upgrade (hash + sender domain etc) doesn't
    leak through every call site."""
    return normalize_subject(subject)


__all__ = [
    "extract_message_id",
    "extract_thread_keys",
    "normalize_subject",
    "subject_thread_key",
]
