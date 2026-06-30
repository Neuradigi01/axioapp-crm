"""whatsapp-platform-upgrade Step 5 — outbound media send tests.

Covers:

  * Each of the four media kinds (image / video / audio / document)
    hits Meta's messages endpoint with the documented envelope shape.
  * Captions are folded into image/video/document but dropped for
    audio (mirrors Meta's spec).
  * `validate_attachment` rejects bad MIME + oversize before any
    network call is made.
  * `upload_to_meta` maps Meta's 413 / 415 / 400 / 5xx into the
    typed `MediaUploadError`'s router-friendly http_status.
  * `WhatsAppAdapter.send()` still emits the text envelope when no
    media attachment is present (regression guard for the existing
    text-only path).

Pure-Python doubles — no Meta, no DB, no FastAPI TestClient.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    WhatsAppSendError,
)
from src.app.core.conversations.media_upload import (
    MAX_CAPTION_LENGTH,
    MediaUploadError,
    captions_supported,
    upload_to_meta,
    validate_attachment,
)

_PHONE_ID = "12345"
_TOKEN = "EAA_test_token"
_API_VERSION = "v19.0"
_TO = "+919876543210"


def _adapter(http_factory) -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id=_PHONE_ID,
        token=_TOKEN,
        app_secret="",
        verify_token="vt",
        api_version=_API_VERSION,
        http_client_factory=http_factory,
    )


def _stub_factory(*, status_code: int = 200, body: dict | None = None):
    """httpx-client factory that always returns the configured response.
    Captures every request the adapter makes on the `calls` list so
    assertions can inspect the envelope shape."""

    calls: list[dict[str, Any]] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, url, json=None, headers=None, files=None):
            calls.append({"url": url, "json": json, "headers": headers, "files": files})
            return httpx.Response(
                status_code,
                json=body if body is not None else {"messages": [{"id": "wamid.media123"}]},
            )

    factory = lambda: _Client()  # noqa: E731
    factory.calls = calls  # type: ignore[attr-defined]
    return factory


# --- validate_attachment ----------------------------------------------


class TestValidateAttachment:
    def test_oversized_image_rejected_with_413(self):
        with pytest.raises(MediaUploadError) as exc:
            validate_attachment(
                type_="image",
                mime_type="image/jpeg",
                size_bytes=10 * 1024 * 1024,  # 10MB > 5MB cap
            )
        assert exc.value.http_status == 413

    def test_bad_mime_for_type_rejected_with_415(self):
        with pytest.raises(MediaUploadError) as exc:
            validate_attachment(
                type_="image",
                mime_type="image/gif",  # GIF not on Meta's image whitelist
                size_bytes=1024,
            )
        assert exc.value.http_status == 415

    def test_unknown_type_rejected_with_422(self):
        with pytest.raises(MediaUploadError) as exc:
            validate_attachment(
                type_="sticker",  # not a supported kind
                mime_type="image/webp",
                size_bytes=1024,
            )
        assert exc.value.http_status == 422

    def test_audio_caption_unsupported(self):
        assert captions_supported("audio") is False
        assert captions_supported("image") is True
        assert captions_supported("video") is True
        assert captions_supported("document") is True


# --- upload_to_meta ----------------------------------------------------


class TestUploadToMeta:
    @pytest.mark.asyncio
    async def test_happy_path_returns_media_id(self):
        factory = _stub_factory(status_code=200, body={"id": "1234567890"})
        result = await upload_to_meta(
            phone_id=_PHONE_ID,
            token=_TOKEN,
            api_version=_API_VERSION,
            file_bytes=b"binary-content",
            mime_type="image/jpeg",
            filename="sofa.jpg",
            http_client_factory=factory,
        )
        assert result == "1234567890"
        call = factory.calls[0]  # type: ignore[attr-defined]
        assert call["url"].endswith(f"/{_PHONE_ID}/media")
        assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"
        # Multipart envelope carries the messaging_product part.
        assert "messaging_product" in call["files"]

    @pytest.mark.asyncio
    async def test_meta_413_maps_to_typed_413(self):
        factory = _stub_factory(status_code=413, body={"error": {}})
        with pytest.raises(MediaUploadError) as exc:
            await upload_to_meta(
                phone_id=_PHONE_ID,
                token=_TOKEN,
                api_version=_API_VERSION,
                file_bytes=b"x" * 1024,
                mime_type="image/jpeg",
                filename="huge.jpg",
                http_client_factory=factory,
            )
        assert exc.value.http_status == 413

    @pytest.mark.asyncio
    async def test_meta_400_maps_to_typed_415(self):
        factory = _stub_factory(status_code=400, body={"error": {}})
        with pytest.raises(MediaUploadError) as exc:
            await upload_to_meta(
                phone_id=_PHONE_ID,
                token=_TOKEN,
                api_version=_API_VERSION,
                file_bytes=b"x",
                mime_type="image/jpeg",
                filename="bad.jpg",
                http_client_factory=factory,
            )
        assert exc.value.http_status == 415

    @pytest.mark.asyncio
    async def test_meta_5xx_maps_to_502(self):
        factory = _stub_factory(status_code=503, body={"error": {}})
        with pytest.raises(MediaUploadError) as exc:
            await upload_to_meta(
                phone_id=_PHONE_ID,
                token=_TOKEN,
                api_version=_API_VERSION,
                file_bytes=b"x",
                mime_type="image/jpeg",
                filename="x.jpg",
                http_client_factory=factory,
            )
        assert exc.value.http_status == 502


# --- WhatsAppAdapter.send() routing -----------------------------------


_ORG_ID = uuid.uuid4()


class TestAdapterMediaSend:
    @pytest.mark.asyncio
    async def test_image_attachment_uses_image_envelope_with_caption(
        self,
    ):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="Check this out",
            attachments=[
                {
                    "type": "image",
                    "media_id": "mid_image_1",
                    "mime_type": "image/jpeg",
                }
            ],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "image"
        assert envelope["image"]["id"] == "mid_image_1"
        assert envelope["image"]["caption"] == "Check this out"

    @pytest.mark.asyncio
    async def test_audio_envelope_drops_caption(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="ignored",
            attachments=[
                {
                    "type": "audio",
                    "media_id": "mid_audio_1",
                    "mime_type": "audio/ogg",
                }
            ],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "audio"
        assert envelope["audio"] == {"id": "mid_audio_1"}
        assert "caption" not in envelope["audio"]

    @pytest.mark.asyncio
    async def test_video_envelope_carries_caption(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="walkthrough",
            attachments=[
                {
                    "type": "video",
                    "media_id": "mid_video_1",
                    "mime_type": "video/mp4",
                }
            ],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "video"
        assert envelope["video"]["caption"] == "walkthrough"

    @pytest.mark.asyncio
    async def test_document_envelope_carries_caption_and_filename(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="quote",
            attachments=[
                {
                    "type": "document",
                    "media_id": "mid_doc_1",
                    "mime_type": "application/pdf",
                    "filename": "quotation.pdf",
                }
            ],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "document"
        assert envelope["document"]["id"] == "mid_doc_1"
        assert envelope["document"]["caption"] == "quote"
        assert envelope["document"]["filename"] == "quotation.pdf"

    @pytest.mark.asyncio
    async def test_inbound_style_attachment_does_not_trigger_media_branch(
        self,
    ):
        """Inbound webhook attachments use `{type, id, sha256}` not
        `{type, media_id}`. The send branch must NOT pick those up
        as media references — otherwise echoing an inbound payload
        would render as a bogus text-less send."""
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="hi",
            attachments=[{"type": "image", "id": "inbound_id", "sha256": "abc"}],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "text"
        assert envelope["text"]["body"] == "hi"

    @pytest.mark.asyncio
    async def test_text_only_send_still_works(self):
        """Regression guard — no attachments still emits text envelope."""
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="hello",
            attachments=[],
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "text"
        assert envelope["text"]["body"] == "hello"

    @pytest.mark.asyncio
    async def test_meta_send_4xx_raises_typed_error(self):
        factory = _stub_factory(status_code=400, body={"error": {}})
        adapter = _adapter(factory)
        with pytest.raises(WhatsAppSendError):
            await adapter.send(
                org_id=_ORG_ID,
                external_id=_TO,
                text="boom",
                attachments=[
                    {
                        "type": "image",
                        "media_id": "mid_x",
                        "mime_type": "image/jpeg",
                    }
                ],
            )


def test_max_caption_length_matches_meta_spec():
    """Sanity: the schema/router cap matches Meta's documented 1024."""
    assert MAX_CAPTION_LENGTH == 1024
