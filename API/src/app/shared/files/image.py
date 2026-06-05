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


# 5 MB cap — matches the contacts-import upload limit; predictable
# memory profile for inline processing.
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


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


def validate_image_upload(data: bytes) -> tuple[str, str]:
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

    if len(data) > MAX_IMAGE_SIZE_BYTES:
        max_mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        raise ImageValidationError(f"Image exceeds the {max_mb} MB cap.")

    detected_mime = magic.from_buffer(data[:2048], mime=True)
    extension = ALLOWED_IMAGE_MIME.get(detected_mime)
    if extension is None:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME))
        raise ImageValidationError(
            f"Unsupported image type {detected_mime!r}. Allowed: {allowed}."
        )

    return detected_mime, extension


__all__ = [
    "ALLOWED_IMAGE_MIME",
    "MAX_IMAGE_SIZE_BYTES",
    "ImageValidationError",
    "validate_image_upload",
]
