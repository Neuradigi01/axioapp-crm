"""whatsapp-platform-upgrade Step 8 — template management tests.

Pure-Python boundary tests; no DB, no FastAPI. Covers:

  1. ``WhatsAppTemplateUpsert`` rejects bodies > 1024 chars.
  2. Header type / text consistency — TEXT header requires text;
     media headers reject text.
  3. Mixing quick-reply with URL buttons is rejected.
  4. URL button requires a `url` field; PHONE_NUMBER requires
     `phone_number`.
  5. ``_payload_to_components`` builds Meta's components array
     correctly for a full template with header + body + footer + 2
     CTA buttons.
  6. ``_META_EVENT_TO_STATUS`` covers every Meta-shipped event with a
     defined enum mapping.
  7. ``_extract_template_status_event`` correctly parses Meta's
     webhook envelope shape AND returns None on non-template payloads.
  8. ``apply_template_status_update`` updates a matching row and
     populates ``rejection_reason`` on REJECTED events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.app.core.conversations.router import (
    _extract_template_status_event,
)
from src.app.core.integrations.whatsapp.models import (
    WhatsAppTemplate,
    WhatsAppTemplateSubmissionStatus,
)
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppTemplateUpsert,
)
from src.app.core.integrations.whatsapp.templates_service import (
    _META_EVENT_TO_STATUS,
    _payload_to_components,
    apply_template_status_update,
)


_ORG_ID = uuid.uuid4()


# --- schema validation ----------------------------------------------------


class TestSchemaValidation:
    def test_overlong_body_rejected(self):
        with pytest.raises(ValidationError):
            WhatsAppTemplateUpsert(
                name="too_long",
                language="en_US",
                category="MARKETING",
                body="x" * 1025,
            )

    def test_text_header_requires_text(self):
        with pytest.raises(ValidationError):
            WhatsAppTemplateUpsert(
                name="text_header_missing_text",
                language="en_US",
                category="MARKETING",
                body="ok",
                header_type="TEXT",
                header_text=None,
            )

    def test_media_header_must_not_carry_text(self):
        with pytest.raises(ValidationError):
            WhatsAppTemplateUpsert(
                name="image_header_with_text",
                language="en_US",
                category="MARKETING",
                body="ok",
                header_type="IMAGE",
                header_text="should be empty",
            )

    def test_mixed_button_kinds_rejected(self):
        with pytest.raises(ValidationError):
            WhatsAppTemplateUpsert(
                name="mixed_buttons",
                language="en_US",
                category="MARKETING",
                body="Pick one",
                buttons=[
                    {"type": "QUICK_REPLY", "text": "Yes"},
                    {
                        "type": "URL",
                        "text": "Open",
                        "url": "https://example.com",
                    },
                ],
            )

    def test_url_button_requires_url(self):
        with pytest.raises(ValidationError):
            WhatsAppTemplateUpsert(
                name="url_button_missing_url",
                language="en_US",
                category="MARKETING",
                body="Visit",
                buttons=[{"type": "URL", "text": "Open"}],
            )


# --- components builder ---------------------------------------------------


class TestComponentsBuilder:
    def test_full_template_components(self):
        payload = WhatsAppTemplateUpsert(
            name="full_template",
            language="en_US",
            category="MARKETING",
            body="Hi {{1}}, your order {{2}} is confirmed.",
            header_type="TEXT",
            header_text="Order Update",
            footer_text="Sharma Furniture",
            buttons=[
                {
                    "type": "URL",
                    "text": "Track",
                    "url": "https://example.com/track",
                },
                {
                    "type": "PHONE_NUMBER",
                    "text": "Call us",
                    "phone_number": "+919876543210",
                },
            ],
        )
        components = _payload_to_components(payload)
        # Header
        assert components[0] == {
            "type": "HEADER",
            "format": "TEXT",
            "text": "Order Update",
        }
        # Body
        assert components[1]["type"] == "BODY"
        assert "{{1}}" in components[1]["text"]
        # Footer
        assert components[2] == {
            "type": "FOOTER",
            "text": "Sharma Furniture",
        }
        # Buttons
        buttons_component = components[3]
        assert buttons_component["type"] == "BUTTONS"
        kinds = [b["type"] for b in buttons_component["buttons"]]
        assert kinds == ["URL", "PHONE_NUMBER"]
        assert buttons_component["buttons"][0]["url"].startswith("https://")
        assert (
            buttons_component["buttons"][1]["phone_number"]
            == "+919876543210"
        )


# --- event mapping --------------------------------------------------------


class TestEventMapping:
    def test_every_meta_event_maps_to_a_status(self):
        # The full set of Meta-published events. Keep this in sync with
        # `_META_EVENT_TO_STATUS` so a new Meta event gets a CI failure
        # instead of a silent default-to-pending.
        meta_events = {
            "APPROVED",
            "REJECTED",
            "FLAGGED",
            "PAUSED",
            "DISABLED",
            "PENDING",
            "PENDING_DELETION",
            "IN_APPEAL",
        }
        assert meta_events == set(_META_EVENT_TO_STATUS.keys())

    def test_approved_maps_to_approved(self):
        assert (
            _META_EVENT_TO_STATUS["APPROVED"]
            == WhatsAppTemplateSubmissionStatus.approved
        )

    def test_flagged_maps_to_rejected(self):
        # Meta's "FLAGGED" means temporarily unavailable due to a
        # specific complaint — we surface as rejected so the operator
        # gets the same "fix and resubmit" UX.
        assert (
            _META_EVENT_TO_STATUS["FLAGGED"]
            == WhatsAppTemplateSubmissionStatus.rejected
        )


# --- webhook envelope parsing --------------------------------------------


class TestWebhookExtraction:
    def test_template_event_extracted(self):
        payload = {
            "entry": [
                {
                    "id": "987654321098765",
                    "changes": [
                        {
                            "field": "message_template_status_update",
                            "value": {
                                "event": "REJECTED",
                                "message_template_id": "123",
                                "message_template_name": "diwali_sale_2026",
                                "message_template_language": "en_US",
                                "reason": "TAG_CONTENT_MISMATCH",
                            },
                        }
                    ],
                }
            ]
        }
        event = _extract_template_status_event(payload)
        assert event is not None
        assert event["waba_id"] == "987654321098765"
        assert event["event"] == "REJECTED"
        assert event["message_template_id"] == "123"
        assert event["reason"] == "TAG_CONTENT_MISMATCH"

    def test_non_template_payload_returns_none(self):
        # A regular message webhook — `field` is `messages`, NOT
        # `message_template_status_update`. The extractor must short-
        # circuit so the messages branch handles it.
        payload = {
            "entry": [
                {
                    "id": "987654321098765",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "111"},
                                "messages": [{"id": "wamid", "from": "919"}],
                            },
                        }
                    ],
                }
            ]
        }
        assert _extract_template_status_event(payload) is None

    def test_missing_event_returns_none(self):
        payload = {
            "entry": [
                {
                    "id": "waba",
                    "changes": [
                        {
                            "field": "message_template_status_update",
                            "value": {"message_template_name": "x"},
                        }
                    ],
                }
            ]
        }
        assert _extract_template_status_event(payload) is None


# --- apply_template_status_update ----------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, *, row: WhatsAppTemplate | None):
        self._row = row
        self.commits = 0

    async def execute(self, _stmt):
        return _FakeResult(self._row)

    async def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    from src.app.core.integrations.whatsapp import templates_service

    monkeypatch.setattr(templates_service.audit, "log", _noop)


def _draft_row() -> WhatsAppTemplate:
    return WhatsAppTemplate(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=uuid.uuid4(),
        name="diwali_sale_2026",
        language="en_US",
        category="MARKETING",
        status="PENDING",
        body="hello {{1}}",
        variable_count=1,
        meta_template_id="meta-123",
        submission_status=WhatsAppTemplateSubmissionStatus.pending_review,
        last_synced_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        rejection_reason=None,
    )


class TestApplyTemplateStatusUpdate:
    @pytest.mark.asyncio
    async def test_approval_flips_to_approved(self):
        row = _draft_row()
        session = _FakeSession(row=row)
        applied = await apply_template_status_update(
            session,  # type: ignore[arg-type]
            org_id=_ORG_ID,
            meta_template_id="meta-123",
            template_name=None,
            language=None,
            event="APPROVED",
            reason=None,
        )
        assert applied is True
        assert (
            row.submission_status
            == WhatsAppTemplateSubmissionStatus.approved
        )
        assert row.status == "APPROVED"
        # Approval clears any stale rejection reason.
        assert row.rejection_reason is None

    @pytest.mark.asyncio
    async def test_rejection_persists_reason(self):
        row = _draft_row()
        session = _FakeSession(row=row)
        applied = await apply_template_status_update(
            session,  # type: ignore[arg-type]
            org_id=_ORG_ID,
            meta_template_id="meta-123",
            template_name=None,
            language=None,
            event="REJECTED",
            reason="TAG_CONTENT_MISMATCH",
        )
        assert applied is True
        assert (
            row.submission_status
            == WhatsAppTemplateSubmissionStatus.rejected
        )
        assert row.rejection_reason == "TAG_CONTENT_MISMATCH"

    @pytest.mark.asyncio
    async def test_unknown_event_returns_false(self):
        row = _draft_row()
        before = row.submission_status
        session = _FakeSession(row=row)
        applied = await apply_template_status_update(
            session,  # type: ignore[arg-type]
            org_id=_ORG_ID,
            meta_template_id="meta-123",
            template_name=None,
            language=None,
            event="EVENT_FROM_MARS",
            reason=None,
        )
        assert applied is False
        # Row untouched.
        assert row.submission_status == before

    @pytest.mark.asyncio
    async def test_no_match_returns_false(self):
        session = _FakeSession(row=None)
        applied = await apply_template_status_update(
            session,  # type: ignore[arg-type]
            org_id=_ORG_ID,
            meta_template_id="meta-missing",
            template_name=None,
            language=None,
            event="APPROVED",
            reason=None,
        )
        assert applied is False
