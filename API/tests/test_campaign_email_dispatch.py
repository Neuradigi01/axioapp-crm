"""Campaigns v1 Step 05 — dispatch helpers + tracking callbacks.

Two groups, both pure Python (no DB):

  1. ``substitute_merge_tags`` + ``render_subject`` / ``render_body``
     from :mod:`core.campaigns.utils`. Confirms named-tag resolution
     against a Contact-shaped stand-in.

  2. ``apply_email_status`` from :mod:`core.campaigns.service` against
     a fake AsyncSession. Confirms forward-only status flow +
     set-once timestamps + idempotent replays.

End-to-end dispatch coverage lands with the browser smoke on Ajay's
Workspace + the migration verification below (per repo memory the
pytest suite runs ~12 min, so we lean on unit tests for fast feedback
on the invariants).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from src.app.core.campaigns.models import CampaignMessage, CampaignMessageStatus
from src.app.core.campaigns.utils import (
    MERGE_TAG_FALLBACK,
    render_body,
    render_subject,
    substitute_merge_tags,
)


# --- Contact stand-in --------------------------------------------------


@dataclass
class _Contact:
    full_name: str | None = "Aditi Sharma"
    email: str | None = "aditi@example.com"
    phone: str | None = "+91-98765-43210"
    custom_data: dict[str, Any] | None = None


class TestSubstituteMergeTags:
    def test_full_name(self):
        out = substitute_merge_tags("Hi {{full_name}}!", _Contact())
        assert out == "Hi Aditi Sharma!"

    def test_first_name_split(self):
        out = substitute_merge_tags("Hi {{first_name}}!", _Contact())
        assert out == "Hi Aditi!"

    def test_last_name_split(self):
        out = substitute_merge_tags("Dear {{last_name}}", _Contact())
        assert out == "Dear Sharma"

    def test_single_token_full_name(self):
        # No surname on file — first_name gets the whole token, last_name empty.
        out = substitute_merge_tags(
            "Hi {{first_name}} {{last_name}}",
            _Contact(full_name="Prince"),
        )
        # Empty last_name falls back to "Customer" (known tag).
        assert out == f"Hi Prince {MERGE_TAG_FALLBACK}"

    def test_contact_namespace(self):
        out = substitute_merge_tags("{{contact.email}}", _Contact())
        assert out == "aditi@example.com"

    def test_custom_data_lookup(self):
        out = substitute_merge_tags(
            "Loyalty: {{custom_data.tier}}",
            _Contact(custom_data={"tier": "Gold"}),
        )
        assert out == "Loyalty: Gold"

    def test_unknown_tag_left_intact(self):
        # Typos should stay visible so the operator notices.
        out = substitute_merge_tags("Hi {{unkown}}!", _Contact())
        assert "{{unkown}}" in out

    def test_missing_full_name_falls_back(self):
        out = substitute_merge_tags(
            "Hi {{first_name}}",
            _Contact(full_name=None),
        )
        assert out == f"Hi {MERGE_TAG_FALLBACK}"

    def test_missing_email_falls_back(self):
        out = substitute_merge_tags(
            "{{email}}",
            _Contact(email=None),
        )
        assert out == MERGE_TAG_FALLBACK

    def test_render_subject_and_body_are_aliases(self):
        c = _Contact()
        assert render_subject("Hi {{first_name}}", c) == "Hi Aditi"
        assert render_body("<p>Hi {{first_name}}</p>", c) == "<p>Hi Aditi</p>"

    def test_empty_source_returns_empty(self):
        assert substitute_merge_tags(None, _Contact()) == ""
        assert substitute_merge_tags("", _Contact()) == ""

    def test_multiple_substitutions(self):
        out = substitute_merge_tags(
            "Hi {{first_name}}, email {{email}} phone {{phone}}",
            _Contact(),
        )
        assert out == "Hi Aditi, email aditi@example.com phone +91-98765-43210"


# --- apply_email_status --------------------------------------------------


class _StubResult:
    def __init__(self, row: CampaignMessage | None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _StubSession:
    """AsyncSession stand-in that returns a pre-loaded CampaignMessage
    row from ``execute`` and records ``commit`` calls. Enough surface
    for ``apply_email_status`` to run without a real DB."""

    def __init__(self, *, row: CampaignMessage | None):
        self._row = row
        self.commits = 0

    async def execute(self, _stmt):  # noqa: ANN001 — statement opaque here
        return _StubResult(self._row)

    async def commit(self):
        self.commits += 1


def _make_row(**overrides: Any) -> CampaignMessage:
    row = CampaignMessage(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        channel_message_id="msg-123",
        status=CampaignMessageStatus.sent,
        sent_at=datetime.now(UTC),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


class TestApplyEmailStatus:
    """Runs ``apply_email_status`` against a fake session — no DB."""

    @pytest.mark.asyncio
    async def test_delivered_transitions_and_stamps(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row()
        session = _StubSession(row=row)
        ts = datetime.now(UTC)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="delivered",
            timestamp=ts,
        )
        assert changed is True
        assert row.status == CampaignMessageStatus.delivered
        assert row.delivered_at == ts
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_opened_forward_only(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row(status=CampaignMessageStatus.delivered)
        session = _StubSession(row=row)
        ts = datetime.now(UTC)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="opened",
            timestamp=ts,
        )
        assert changed is True
        assert row.status == CampaignMessageStatus.opened
        assert row.opened_at == ts

    @pytest.mark.asyncio
    async def test_opened_idempotent_replay(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row(
            status=CampaignMessageStatus.opened,
            opened_at=datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        )
        session = _StubSession(row=row)
        later = datetime(2026, 7, 16, 11, 0, tzinfo=UTC)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="opened",
            timestamp=later,
        )
        # No change — status already opened, opened_at already set.
        assert changed is False
        assert row.opened_at == datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_clicked_transitions_from_opened(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row(status=CampaignMessageStatus.opened)
        session = _StubSession(row=row)
        ts = datetime.now(UTC)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="clicked",
            timestamp=ts,
        )
        assert changed is True
        assert row.status == CampaignMessageStatus.clicked
        assert row.first_click_at == ts

    @pytest.mark.asyncio
    async def test_bounced_flips_failed_and_stamps_type(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row()
        session = _StubSession(row=row)
        ts = datetime.now(UTC)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="bounced",
            timestamp=ts,
            bounce_type="hard",
        )
        assert changed is True
        assert row.status == CampaignMessageStatus.failed
        assert row.bounced_at == ts
        assert row.bounce_type == "hard"
        assert row.error is not None

    @pytest.mark.asyncio
    async def test_late_delivered_on_failed_row_is_noop(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row(status=CampaignMessageStatus.failed)
        session = _StubSession(row=row)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="delivered",
            timestamp=datetime.now(UTC),
        )
        assert changed is False
        assert row.status == CampaignMessageStatus.failed

    @pytest.mark.asyncio
    async def test_unknown_message_id_returns_false(self):
        from src.app.core.campaigns.service import apply_email_status

        session = _StubSession(row=None)
        changed = await apply_email_status(
            session,
            channel_message_id="never-sent",
            email_status="delivered",
            timestamp=datetime.now(UTC),
        )
        assert changed is False

    @pytest.mark.asyncio
    async def test_unknown_status_returns_false(self):
        from src.app.core.campaigns.service import apply_email_status

        row = _make_row()
        session = _StubSession(row=row)
        changed = await apply_email_status(
            session,
            channel_message_id="msg-123",
            email_status="not-a-real-status",
            timestamp=datetime.now(UTC),
        )
        assert changed is False
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_empty_channel_message_id_returns_false(self):
        from src.app.core.campaigns.service import apply_email_status

        session = _StubSession(row=_make_row())
        changed = await apply_email_status(
            session,
            channel_message_id="",
            email_status="delivered",
            timestamp=datetime.now(UTC),
        )
        assert changed is False
