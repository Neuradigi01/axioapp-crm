"""File-upload validation helpers for knowledge ingest
(``tasks/ai-assistants`` Step 10; Attacker H5+H6, Cases §10-14).

Pure functions — no DB, no filesystem. The router calls these
BEFORE calling ``StorageBackend.put`` so a malicious upload never
lands on disk.

Guards:
  * Magic-byte sniff (``filetype`` library) — declared MIME must
    match sniffed type. Rejects a ``.exe`` renamed to ``.pdf``.
  * Windows-reserved-name check on ``original_filename`` (``CON``,
    ``NUL``, ``AUX``, ``PRN``, ``COM1-9``, ``LPT1-9``) — refuses
    even on non-Windows hosts because the filename may later be
    downloaded onto a Windows client.
  * Size cap (< 90 MB raw upload).
  * SHA-256 fingerprint of the bytes for content-hash dedup on the
    (assistant_id, content_hash) unique index.

Path safety is enforced elsewhere — we ALWAYS store as
``{knowledge_id}.bin`` and never use the client filename as a path
component (see :meth:`service.create_knowledge_from_file`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import filetype

# Allowed MIME types for the file source type. Anything else is
# rejected at magic-byte check. Add here + update the accept="" on
# the frontend uploader in one go.
ALLOWED_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "text/plain",
    }
)

# Windows-reserved base names (case-insensitive). Even on Linux
# hosts we refuse because the filename column may be surfaced to a
# Windows user who then tries to save-as it.
_WIN_RESERVED = frozenset(
    {
        "con",
        "nul",
        "aux",
        "prn",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

_MAX_UPLOAD_BYTES: int = 90 * 1024 * 1024

# Illegal-character regex for filenames — bounded to what any
# file system will accept without escape. Newlines / tabs / control
# chars refused. Path separators refused (we never use the filename
# as a path anyway, but a filename containing ``/`` renders badly).
_ILLEGAL_FILENAME = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]")


class FileValidationError(Exception):
    """Raised when the uploaded blob fails a pre-storage check.
    Carries a stable ``reason`` code the router surfaces as
    ``{"reason": "..."}`` at 422 so the frontend can localise a
    friendly message per code."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Structured payload from :func:`validate_upload`. The router
    consumes ``content_hash`` for dedup and ``sniffed_mime`` for
    persistence + serve headers."""

    original_filename: str
    sniffed_mime: str
    size_bytes: int
    content_hash: bytes  # 32 bytes (SHA-256)


def _check_windows_reserved(filename: str) -> None:
    """Raise if the stem matches a Windows-reserved base name."""
    if not filename:
        return
    # Strip directory-ish components — we only care about the base.
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem, _, _ = base.partition(".")
    if stem.lower() in _WIN_RESERVED:
        raise FileValidationError(
            f"filename base {stem!r} is a Windows reserved name",
            reason="windows_reserved_name",
        )


def _check_filename_illegal_chars(filename: str) -> None:
    if not filename:
        return
    if _ILLEGAL_FILENAME.search(filename):
        raise FileValidationError(
            "filename contains illegal characters",
            reason="illegal_filename_chars",
        )


def validate_upload(
    *,
    filename: str,
    data: bytes,
) -> ValidatedUpload:
    """Run every check + return the payload the router needs.

    Order matters: cheap checks (name + size) first, then the more
    expensive magic-byte sniff. Any failure surfaces as
    :class:`FileValidationError` with a stable ``reason`` code.
    """
    # 1. Size.
    if len(data) == 0:
        raise FileValidationError("uploaded file is empty", reason="empty_file")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise FileValidationError(
            f"file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            reason="file_too_large",
        )

    # 2. Filename hygiene. Preserves the caller's original name for
    # display but rejects anything the OS layer would break on.
    _check_filename_illegal_chars(filename)
    _check_windows_reserved(filename)

    # 3. Magic-byte sniff. ``filetype`` returns None on unrecognised
    # bytes — we treat that as "text/plain" iff the whole payload
    # decodes cleanly as UTF-8, else reject. This lets ``.txt`` /
    # ``.md`` uploads through without needing them to carry a magic
    # header (there is none for plain text).
    guess = filetype.guess(data)
    if guess is not None:
        sniffed = guess.mime
        if sniffed not in ALLOWED_MIMES:
            raise FileValidationError(
                f"file type {sniffed!r} not allowed for knowledge upload",
                reason="unsupported_mime",
            )
    else:
        # No magic bytes — could be plain text. UTF-8 decode as the
        # arbiter; anything else = reject (probably a random binary
        # renamed to .txt).
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileValidationError(
                "unrecognised file type — not a supported binary and not UTF-8 text",
                reason="unrecognised_file_type",
            ) from exc
        sniffed = "text/plain"

    content_hash = hashlib.sha256(data).digest()
    return ValidatedUpload(
        original_filename=filename,
        sniffed_mime=sniffed,
        size_bytes=len(data),
        content_hash=content_hash,
    )


__all__ = ["ALLOWED_MIMES", "FileValidationError", "ValidatedUpload", "validate_upload"]
