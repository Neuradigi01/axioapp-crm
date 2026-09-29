"""Storage key guard.

Every key and prefix handed to a `StorageBackend` passes through here
before it touches disk or an object store. Object stores do not
normalise keys (``a/../b`` is a literal key on R2, a real traversal on
disk), so the rules below reject anything whose meaning could differ
between backends instead of trying to normalise it.
"""

from __future__ import annotations

import mimetypes
import uuid

#: Top-level folders that sit *before* the org id instead of after it
#: (``catalog/{org}/…``, ``imports/{org}/…`` for contact imports).
_NAMESPACED_ROOTS = frozenset({"catalog", "imports"})


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def validate_key(key: str) -> str:
    """Return `key` unchanged if it is a safe storage-relative key.

    Rejects empty keys, leading ``/``, backslashes, NUL / control
    characters, empty segments (``a//b``) and ``.`` / ``..`` segments.
    Raises `ValueError` otherwise.
    """
    if not key:
        raise ValueError("storage key is empty")
    if key.startswith("/"):
        raise ValueError(f"storage key {key!r} must be relative")
    if "\\" in key:
        raise ValueError(f"storage key {key!r} contains a backslash")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
        raise ValueError(f"storage key {key!r} contains a control character")
    for segment in key.split("/"):
        if segment in ("", ".", ".."):
            raise ValueError(f"storage key {key!r} has an invalid segment")
    return key


def validate_prefix(prefix: str) -> str:
    """Return `prefix` normalised to end in ``/`` for prefix operations
    (`delete_directory`, `list_keys`).

    Beyond `validate_key`, the prefix must be scoped to one org: its
    first segment is an org UUID, or it is ``catalog/<uuid>`` /
    ``imports/<uuid>``. An empty or unscoped prefix would match every
    tenant in the bucket, so it is refused.
    """
    validate_key(prefix.rstrip("/"))
    segments = prefix.rstrip("/").split("/")
    if _is_uuid(segments[0]):
        pass
    elif segments[0] in _NAMESPACED_ROOTS and len(segments) > 1 and _is_uuid(segments[1]):
        pass
    else:
        raise ValueError(f"storage prefix {prefix!r} is not scoped to an org")
    return prefix.rstrip("/") + "/"


def assert_org_key(org_id: uuid.UUID, key: str) -> str:
    """Return `key` if it belongs to `org_id`, else raise
    `FileNotFoundError` so callers answer 404.

    Used on keys read back from DB rows before a read, so a row that
    carries another org's key can never serve that org's file.
    """
    validate_key(key)
    org = str(org_id)
    segments = key.split("/")
    if segments[0] == org:
        return key
    if segments[0] in _NAMESPACED_ROOTS and len(segments) > 1 and segments[1] == org:
        return key
    raise FileNotFoundError(key)


def content_type_for(key: str) -> str:
    """Best-effort MIME type from the key's extension."""
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"
