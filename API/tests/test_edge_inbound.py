"""whatsapp-platform-upgrade Step 28 — edge inbound type tests.

Pure-Python boundary coverage of:
  * `parse_webhook` for ``location`` / ``contacts`` / ``sticker`` —
    each populates ``attachments[]`` with the documented Meta shape
    and falls back to a readable ``text`` preview for the inbox.
  * `_first_location_attachment` discriminator (Step 28 outbound).
  * `_build_location_envelope` shape matches Meta's docs.

Cases:
  1.  Inbound location with all fields → attachment + 📍 name preview.
  2.  Inbound location without name uses address as preview.
  3.  Inbound location without name + address falls back to generic.
  4.  Inbound location missing latitude is ignored gracefully.
  5.  Inbound contacts populates formatted_name + primary_phone.
  6.  Inbound contacts handles missing emails / phones gracefully.
  7.  Inbound contacts preserves the raw `cards` array for forensics.
  8.  Inbound sticker captures id + animated flag + 🟦 preview.
  9.  Inbound sticker without id is ignored.
 10.  `_first_location_attachment` picks the location row.
 11.  `_first_location_attachment` returns None when none present.
 12.  `_first_location_attachment` ignores rows missing lat/lng.
 13.  `_build_location_envelope` shape (lat/lng floats + name + address).
 14.  `_build_location_envelope` skips empty name / address.
"""
from __future__ import annotations

import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    _build_location_envelope,
    _first_location_attachment,
)


def _adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id="phone-x",
        token="token-x",
        app_secret="secret-x",
        verify_token="verify-x",
        api_version="v19.0",
    )


def _wrap_message(message: dict) -> dict:
    return {
        "entry": [{"changes": [{"value": {"messages": [message]}}]}]
    }


class TestInboundLocation:
    def test_full_payload(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "location",
            "location": {
                "latitude": 19.0760,
                "longitude": 72.8777,
                "name": "Sharma Furniture",
                "address": "123 Andheri West, Mumbai",
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        loc = next(
            (a for a in parsed.attachments if a.get("type") == "location"),
            None,
        )
        assert loc is not None
        assert loc["latitude"] == 19.0760
        assert loc["longitude"] == 72.8777
        assert loc["name"] == "Sharma Furniture"
        assert loc["address"] == "123 Andheri West, Mumbai"
        # Preview uses the name when present.
        assert parsed.text == "📍 Sharma Furniture"

    def test_address_only_preview(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "location",
            "location": {
                "latitude": 19.0,
                "longitude": 72.8,
                "address": "Mumbai",
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        assert parsed.text == "📍 Mumbai"

    def test_no_label_fallback_preview(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "location",
            "location": {"latitude": 19.0, "longitude": 72.8},
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        assert parsed.text == "📍 Shared location"

    def test_missing_latitude_ignored(self):
        # Meta should never ship this but we don't want to crash if
        # the field is corrupted in flight.
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "location",
            "location": {"longitude": 72.8},
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        assert not any(
            a.get("type") == "location" for a in parsed.attachments
        )


class TestInboundContacts:
    def test_primary_card_extracted(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "contacts",
            "contacts": [
                {
                    "name": {"formatted_name": "Ada Lovelace"},
                    "phones": [{"phone": "+44 20 1234 5678"}],
                    "emails": [{"email": "ada@example.test"}],
                }
            ],
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        card = next(
            (a for a in parsed.attachments if a.get("type") == "contacts"),
            None,
        )
        assert card is not None
        assert card["formatted_name"] == "Ada Lovelace"
        assert card["primary_phone"] == "+44 20 1234 5678"
        assert card["primary_email"] == "ada@example.test"
        assert parsed.text == "📇 Shared contact: Ada Lovelace"

    def test_missing_optional_fields(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "contacts",
            "contacts": [
                {
                    "name": {"formatted_name": "Bob"},
                    # No phones, no emails — Meta will accept this.
                }
            ],
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        card = next(
            (a for a in parsed.attachments if a.get("type") == "contacts"),
            None,
        )
        assert card is not None
        assert card["primary_phone"] is None
        assert card["primary_email"] is None
        assert card["formatted_name"] == "Bob"

    def test_raw_cards_preserved(self):
        cards_payload = [
            {
                "name": {"formatted_name": "Ada"},
                "phones": [{"phone": "+1 555"}],
            },
            {
                "name": {"formatted_name": "Bob"},
                "phones": [{"phone": "+1 666"}],
            },
        ]
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "contacts",
            "contacts": cards_payload,
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        card = next(
            (a for a in parsed.attachments if a.get("type") == "contacts"),
            None,
        )
        # Whole array preserved for forensics + multi-card UI later.
        assert card["cards"] == cards_payload


class TestInboundSticker:
    def test_basic(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "sticker",
            "sticker": {
                "id": "media-1",
                "mime_type": "image/webp",
                "animated": True,
                "sha256": "abc",
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        st = next(
            (a for a in parsed.attachments if a.get("type") == "sticker"),
            None,
        )
        assert st is not None
        assert st["id"] == "media-1"
        assert st["mime_type"] == "image/webp"
        assert st["animated"] is True
        assert parsed.text == "🟦 Sticker"

    def test_sticker_without_id_ignored(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "sticker",
            "sticker": {"mime_type": "image/webp"},
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        assert not any(
            a.get("type") == "sticker" for a in parsed.attachments
        )


class TestOutboundLocationHelpers:
    def test_first_location_picks_location(self):
        attachments = [
            {"type": "image", "media_id": "m1"},
            {"type": "location", "latitude": 19.0, "longitude": 72.8},
        ]
        loc = _first_location_attachment(attachments)
        assert loc is not None
        assert loc["latitude"] == 19.0

    def test_first_location_none_when_absent(self):
        attachments = [{"type": "image", "media_id": "m1"}]
        assert _first_location_attachment(attachments) is None

    def test_first_location_ignores_missing_coords(self):
        # Defensive: a location row missing lat/lng shouldn't poison
        # the dispatcher (we'd ship Meta a malformed envelope).
        attachments = [{"type": "location", "latitude": 19.0}]
        assert _first_location_attachment(attachments) is None

    def test_build_envelope_shape(self):
        envelope = _build_location_envelope(
            to="919999988888",
            attachment={
                "type": "location",
                "latitude": 19.0760,
                "longitude": 72.8777,
                "name": "Sharma Furniture",
                "address": "Mumbai",
            },
        )
        assert envelope["type"] == "location"
        assert envelope["to"] == "919999988888"
        block = envelope["location"]
        assert block["latitude"] == 19.0760
        assert block["longitude"] == 72.8777
        assert block["name"] == "Sharma Furniture"
        assert block["address"] == "Mumbai"

    def test_build_envelope_skips_empty_strings(self):
        envelope = _build_location_envelope(
            to="919999988888",
            attachment={
                "type": "location",
                "latitude": 19.0,
                "longitude": 72.8,
                "name": "  ",
                "address": None,
            },
        )
        block = envelope["location"]
        assert "name" not in block
        assert "address" not in block
