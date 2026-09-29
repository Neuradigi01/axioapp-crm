"""Public file patterns — which storage keys may be served without login.

A module that shows images to logged-out visitors (public store,
listings, chat widget) declares the key shapes it writes in its
`ModuleDescriptor.public_files`. Anything no module declares stays
private: it is reachable only through that module's authenticated,
org-scoped endpoints.

Pattern syntax is one token per ``/``-separated key segment, and a key
matches only when it has exactly as many segments:

* ``{uuid}`` — the segment must parse as a UUID;
* ``*`` — any single segment (the file name); only allowed last;
* anything else — a literal folder name (``[a-z0-9_-]+``).

The pattern must be scoped to one org (first segment ``{uuid}``, or a
literal followed by ``{uuid}``) and end in ``*``, so no pattern can
expose a whole tenant's folder or a folder shared across tenants.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from src.app.shared.storage.keys import validate_key

UUID_SEGMENT = "{uuid}"
ANY_SEGMENT = "*"
_LITERAL_RE = re.compile(r"^[a-z0-9_-]+$")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class PublicFilePattern:
    """A parsed public-file pattern. Build with `parse`."""

    segments: tuple[str, ...]

    @classmethod
    def parse(cls, pattern: str) -> PublicFilePattern:
        segments = tuple(pattern.split("/"))
        for index, segment in enumerate(segments):
            if segment == ANY_SEGMENT:
                if index != len(segments) - 1:
                    raise ValueError(f"public file pattern {pattern!r}: '*' must be last")
            elif segment != UUID_SEGMENT and not _LITERAL_RE.match(segment):
                raise ValueError(f"public file pattern {pattern!r}: bad segment {segment!r}")
        if segments[-1] != ANY_SEGMENT:
            raise ValueError(f"public file pattern {pattern!r} must end in '*'")
        org_scoped = segments[0] == UUID_SEGMENT or (
            len(segments) > 2 and segments[0] != ANY_SEGMENT and segments[1] == UUID_SEGMENT
        )
        if not org_scoped:
            raise ValueError(f"public file pattern {pattern!r} is not scoped to an org")
        return cls(segments=segments)

    def matches(self, key: str) -> bool:
        parts = key.split("/")
        if len(parts) != len(self.segments):
            return False
        for token, part in zip(self.segments, parts, strict=True):
            if token == UUID_SEGMENT:
                if not _is_uuid(part):
                    return False
            elif token != ANY_SEGMENT and token != part:
                return False
        return True


def is_public_key(key: str, patterns: Iterable[PublicFilePattern]) -> bool:
    """True when `key` is a safe storage key matching any pattern."""
    try:
        validate_key(key)
    except ValueError:
        return False
    return any(pattern.matches(key) for pattern in patterns)
