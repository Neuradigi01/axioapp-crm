"""WhatsApp outbound media upload helper.

Meta's Cloud API requires every outbound media message to reference a
``media_id`` minted from a prior multipart upload to
``POST /{phone_id}/media``. This module owns that upload + a small
validation surface (MIME whitelist + per-type size cap) so the
adapter's ``send()`` stays focused on the messages-endpoint envelope.

Why a separate module instead of folding into the adapter:

* The upload + send pair is a two-call choreography. Co-locating the
  upload here lets ``send()`` stay typed against ``media_id`` strings
  rather than raw bytes, and lets unit tests inject a stub uploader
  without mocking the whole adapter.
* The validation table (MIME + size) is reference data the router
  also reads from to reject bad uploads before they hit the network.

Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/
reference/media
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# Per-type MIME whitelist + size cap (bytes). Source: Meta Cloud API
# "Supported Media Types" table. Caps are absolute — we reject at the
# router boundary so a 20MB image never hits the Graph API.
#
# These caps are slightly conservative on documents (Meta allows 100MB
# but our reverse proxy default upload limit is lower; revisit when
# infra confirms it can stream larger payloads safely).
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}
_VIDEO_MIME_TYPES = {"video/mp4", "video/3gpp"}
_AUDIO_MIME_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/amr",
    "audio/ogg",
}
_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
}


# Per Meta's published limits as of v19.0. Tighten if your reverse
# proxy caps the body smaller — pre-rejecting here is friendlier than
# a generic 413 from the edge.
_MAX_SIZE_BYTES = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
}


_MIME_BY_TYPE = {
    "image": _IMAGE_MIME_TYPES,
    "video": _VIDEO_MIME_TYPES,
    "audio": _AUDIO_MIME_TYPES,
    "document": _DOCUMENT_MIME_TYPES,
}


# Media kinds Meta supports captions on; audio is the odd one out (the
# Cloud API silently drops captions on audio messages, so we surface
# the same rule to callers by ignoring the field server-side).
_CAPTIONS_SUPPORTED = {"image", "video", "document"}


MAX_CAPTION_LENGTH = 1024


class MediaUploadError(Exception):
    """Raised when validation fails or Meta rejects the upload."""

    def __init__(self, *, http_status: int, user_message: str) -> None:
        super().__init__(user_message)
        self.http_status = http_status
        self.user_message = user_message


def validate_attachment(
    *, type_: str, mime_type: str, size_bytes: int
) -> None:
    """Pre-flight check at the router boundary. Raises ``MediaUploadError``
    with the appropriate HTTP status so the caller can pass it through.

    Bundling these three checks keeps the upload helper's call site
    cleaner: the router runs validation, then opens the connection;
    the helper trusts what reaches it."""
    if type_ not in _MIME_BY_TYPE:
        raise MediaUploadError(
            http_status=422,
            user_message=(
                f"Unsupported media type {type_!r}. Allowed: "
                f"{', '.join(sorted(_MIME_BY_TYPE))}."
            ),
        )
    if mime_type not in _MIME_BY_TYPE[type_]:
        raise MediaUploadError(
            http_status=415,
            user_message=(
                f"MIME type {mime_type!r} is not allowed for "
                f"{type_!r} messages."
            ),
        )
    cap = _MAX_SIZE_BYTES[type_]
    if size_bytes > cap:
        raise MediaUploadError(
            http_status=413,
            user_message=(
                f"File is too large ({size_bytes} bytes) — Meta caps "
                f"{type_} at {cap} bytes."
            ),
        )


def captions_supported(type_: str) -> bool:
    """Whether Meta's media envelope honours a caption for this type.

    Audio messages don't carry captions; surface that to callers so the
    UI can disable the field rather than silently drop the value."""
    return type_ in _CAPTIONS_SUPPORTED


async def upload_to_meta(
    *,
    phone_id: str,
    token: str,
    api_version: str,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    http_client_factory=None,
) -> str:
    """POST ``{phone_id}/media`` (multipart) and return the ``media_id``.

    ``messaging_product=whatsapp`` is required by Meta on every upload.
    The ``file`` part name is fixed by spec — don't rename it. We force
    the filename on the multipart envelope because Meta uses it to set
    the download filename when the recipient saves the attachment.

    Raises ``MediaUploadError`` on any non-2xx; the caller maps to the
    router-friendly HTTP status."""
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file": (filename, file_bytes, mime_type),
        "messaging_product": (None, "whatsapp"),
        "type": (None, mime_type),
    }
    factory = http_client_factory or (
        lambda: httpx.AsyncClient(timeout=60.0)
    )
    async with factory() as client:
        response = await client.post(url, headers=headers, files=files)
    if response.status_code >= 400:
        logger.warning(
            "whatsapp media upload failed status=%s body=%s",
            response.status_code,
            response.text[:300],
        )
        # Map common Meta rejections to friendlier user-facing messages.
        if response.status_code == 413:
            raise MediaUploadError(
                http_status=413,
                user_message=(
                    "Meta rejected the file as too large — try a smaller "
                    "version."
                ),
            )
        if response.status_code in (400, 415):
            raise MediaUploadError(
                http_status=415,
                user_message=(
                    "Meta refused the file type — make sure the MIME "
                    "matches the chosen media kind."
                ),
            )
        raise MediaUploadError(
            http_status=502,
            user_message=(
                f"Meta media upload failed: HTTP {response.status_code}."
            ),
        )
    body = response.json()
    media_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(media_id, str) or not media_id:
        raise MediaUploadError(
            http_status=502,
            user_message=(
                "Meta returned no media_id — please retry."
            ),
        )
    return media_id


__all__ = [
    "MAX_CAPTION_LENGTH",
    "MediaUploadError",
    "captions_supported",
    "upload_to_meta",
    "validate_attachment",
]
