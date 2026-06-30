"""whatsapp-platform-upgrade Step 11 — business profile editor tests.

Pure-Python boundary tests covering schema validation + payload
shapes. End-to-end Meta-roundtrip is covered by integration suite.

Cases:
  1. About over 139 chars rejected.
  2. Description over 512 chars rejected.
  3. Too many websites (>2) rejected.
  4. Business hours interval requires `HH:MM` shape.
  5. Patch with no fields validates (no-op save).
  6. `_extract_meta_error` parses Meta's error envelope.
  7. Picture MIME validation in upload service.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from src.app.core.integrations.whatsapp.business_profile import (
    BusinessProfileError,
    _extract_meta_error,
    upload_picture,
)
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppBusinessHoursDay,
    WhatsAppBusinessHoursInterval,
    WhatsAppBusinessProfilePatch,
)


class TestSchemaValidation:
    def test_about_over_139_chars_rejected(self):
        with pytest.raises(ValidationError):
            WhatsAppBusinessProfilePatch(about="x" * 140)

    def test_description_over_512_chars_rejected(self):
        with pytest.raises(ValidationError):
            WhatsAppBusinessProfilePatch(description="x" * 513)

    def test_too_many_websites_rejected(self):
        with pytest.raises(ValidationError):
            WhatsAppBusinessProfilePatch(
                websites=["a", "b", "c"],  # max 2
            )

    def test_interval_requires_hh_mm_shape(self):
        with pytest.raises(ValidationError):
            WhatsAppBusinessHoursInterval(open="10am", close="7pm")

    def test_valid_interval(self):
        iv = WhatsAppBusinessHoursInterval(open="10:00", close="19:00")
        assert iv.open == "10:00"

    def test_empty_patch_validates(self):
        # No fields supplied — service treats this as a no-op (no Meta
        # call, no audit row). Pydantic must accept it.
        patch = WhatsAppBusinessProfilePatch()
        assert patch.model_dump(exclude_unset=True) == {}

    def test_business_hours_day_with_intervals(self):
        day = WhatsAppBusinessHoursDay(
            day=0,
            intervals=[
                {"open": "10:00", "close": "13:00"},
                {"open": "14:00", "close": "19:00"},
            ],
        )
        assert len(day.intervals) == 2


class TestMetaErrorExtraction:
    def test_well_formed_meta_error(self):
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": "(#100) Invalid parameter",
                    "code": 100,
                }
            },
        )
        assert _extract_meta_error(response) == "(#100) Invalid parameter"

    def test_non_json_falls_back_to_text(self):
        response = httpx.Response(500, content=b"Internal Server Error")
        # Falls back to "HTTP 500: ..." rather than crashing.
        assert "500" in _extract_meta_error(response)


class TestUploadPictureValidation:
    @pytest.mark.asyncio
    async def test_rejects_non_jpeg_png(self):
        # No session needed — the MIME guard raises before any DB / Meta
        # call. Just pass None and assert the right error surfaces.
        with pytest.raises(BusinessProfileError) as exc_info:
            await upload_picture(
                None,  # type: ignore[arg-type]
                actor_id=None,  # type: ignore[arg-type]
                file_bytes=b"\x00\x01\x02",
                mime_type="image/gif",
            )
        assert exc_info.value.http_status == 400
        assert "JPEG or PNG" in exc_info.value.user_message

    @pytest.mark.asyncio
    async def test_rejects_oversize(self):
        with pytest.raises(BusinessProfileError) as exc_info:
            await upload_picture(
                None,  # type: ignore[arg-type]
                actor_id=None,  # type: ignore[arg-type]
                file_bytes=b"\x00" * (5 * 1024 * 1024 + 1),
                mime_type="image/jpeg",
            )
        assert exc_info.value.http_status == 413
        assert "5 MB" in exc_info.value.user_message
