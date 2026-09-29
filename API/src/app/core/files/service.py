"""Public file serving — `/files/{key}`.

Serves only keys that a module declared in `ModuleDescriptor.public_files`
AND whose stored type is a raster image. Every other key answers 404 —
including private blobs that exist (call recordings, imports, email
attachments, AI knowledge files), which are reachable only through
their module's authenticated endpoints. The allowlist check runs before
any storage call or ETag comparison, so `If-None-Match` cannot be used
to probe whether a private key exists.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import HTTPException, status

from src.app.core.module_registry import registry
from src.app.shared.files.image import ALLOWED_IMAGE_MIME
from src.app.shared.storage import get_storage
from src.app.shared.storage.public_patterns import is_public_key

logger = logging.getLogger(__name__)

#: Only raster image types are ever served publicly — never SVG, HTML
#: or anything a browser could execute.
PUBLIC_IMAGE_TYPES = frozenset(ALLOWED_IMAGE_MIME)


@dataclass(frozen=True, slots=True)
class PublicFile:
    """A public file ready to send. `body` is None when the client's
    cached copy is current (answer 304)."""

    etag: str
    content_type: str
    size: int
    body: AsyncIterator[bytes] | None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")


def _etag_matches(etag: str, if_none_match: str | None) -> bool:
    if not if_none_match:
        return False
    candidates = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return etag in candidates or "*" in candidates


async def open_public_file(key: str, *, if_none_match: str | None) -> PublicFile:
    """Resolve `key` to a streamable public image, or raise 404 / 502."""
    if not is_public_key(key, registry.public_file_patterns()):
        raise _not_found()

    storage = get_storage()
    try:
        stat = await storage.stat(key)
    except (FileNotFoundError, ValueError) as exc:
        raise _not_found() from exc
    except Exception as exc:
        logger.exception("files: storage stat failed for public key")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="file storage unavailable"
        ) from exc

    if stat.content_type not in PUBLIC_IMAGE_TYPES:
        raise _not_found()

    etag = f'"{stat.etag}"'
    if _etag_matches(etag, if_none_match):
        return PublicFile(etag=etag, content_type=stat.content_type, size=stat.size, body=None)
    return PublicFile(
        etag=etag,
        content_type=stat.content_type,
        size=stat.size,
        body=storage.open_stream(key),
    )
