"""Image-upload validation using libmagic.

`python-magic` reads the file's actual bytes (not the filename or the
client-supplied Content-Type) and reports its real MIME type. That's
the only defence against a renamed `.exe` masquerading as `.jpg` —
filename and Content-Type are both attacker-controlled.

Catalog covers (and any future image-upload point) route through
here so size + format rules stay consistent.
"""

from __future__ import annotations

import magic
from fastapi import HTTPException, status

# 5 MB cap — matches the contacts-import upload limit; predictable
# memory profile for inline processing.
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

# Field / job-site photos straight from a phone camera run larger than
# catalog covers; 10 MB matches ``MAX_FILE_SIZE_MB`` in config.env.
PHOTO_MAX_BYTES = 10 * 1024 * 1024


# Catalog covers in v1. GIF/BMP intentionally excluded — photo
# formats only. Maps MIME → extension; extension is derived from
# the detected MIME, never the uploaded filename.
ALLOWED_IMAGE_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ImageValidationError(ValueError):
    """Raised when an upload fails size / MIME checks.

    Callers translate this into a 400 HTTPException so the message
    reaches the client untouched."""


def validate_image_upload(data: bytes, *, max_bytes: int = MAX_IMAGE_SIZE_BYTES) -> tuple[str, str]:
    """Validate raw upload bytes and return `(mime, extension)`.

    Stages:
      1. Empty / oversize → reject before doing magic-byte work.
      2. `magic.from_buffer(data[:2048], mime=True)` — read just the
         first 2 KB; that's all libmagic needs for image signatures.
      3. Whitelist check — anything outside `ALLOWED_IMAGE_MIME`
         (PDF renamed `.jpg`, GIF, SVG, etc.) is rejected.
    """
    if not data:
        raise ImageValidationError("Empty file.")

    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise ImageValidationError(f"Image exceeds the {max_mb} MB cap.")

    detected_mime = magic.from_buffer(data[:2048], mime=True)
    extension = ALLOWED_IMAGE_MIME.get(detected_mime)
    if extension is None:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME))
        raise ImageValidationError(f"Unsupported image type {detected_mime!r}. Allowed: {allowed}.")

    return detected_mime, extension


def require_image_upload(data: bytes, *, max_bytes: int = MAX_IMAGE_SIZE_BYTES) -> tuple[str, str]:
    """`validate_image_upload`, translated to HTTP 422 for services that
    have no domain-specific error mapping of their own."""
    try:
        return validate_image_upload(data, max_bytes=max_bytes)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


__all__ = [
    "ALLOWED_IMAGE_MIME",
    "MAX_IMAGE_SIZE_BYTES",
    "PHOTO_MAX_BYTES",
    "ImageValidationError",
    "require_image_upload",
    "validate_image_upload",
]
