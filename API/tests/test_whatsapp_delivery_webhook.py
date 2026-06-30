"""Step 3.5.12 — `parse_statuses` + `apply_meta_status` unit tests.

The full webhook routing (phone_id lookup → signature verify → context
set → dispatch) needs a real DB session + httpx; covered by manual
smoke against a Meta test number. Here we lock down the pure parsing
helpers + the forward-only status state machine the routing depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.app.core.campaigns import service as campaigns_service
from src.app.core.campaigns.models import (
    CampaignMessage,
    CampaignMessageStatus,
)
from src.app.core.conversations.adapters.whatsapp import (
    parse_statuses,
)

# --- parse_statuses ------------------------------------------------------


class TestParseStatuses:
    def test_basic_delivered_event(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.HBgM...",
                                        "status": "delivered",
                                        "recipient_id": "919876543210",
                                        "timestamp": "1700000000",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = parse_statuses(payload)
        assert len(events) == 1
        e = events[0]
        assert e.channel_message_id == "wamid.HBgM..."
        assert e.status == "delivered"
        assert e.recipient_id == "919876543210"
        assert e.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)
        assert e.error is None

    def test_failed_event_includes_error(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.X",
                                        "status": "failed",
                                        "recipient_id": "919999999999",
                                        "timestamp": "1700000100",
                                        "errors": [
                                            {
                                                "code": 131056,
                                                "title": "Recipient not on WhatsApp",
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = parse_statuses(payload)
        assert len(events) == 1
        assert events[0].status == "failed"
        assert events[0].error == "Recipient not on WhatsApp"

    def test_messages_only_payload_returns_empty(self):
        """Inbound message payloads carry `messages[]` not
        `statuses[]` — `parse_statuses` returns `[]` so the caller
        falls through to the inbound-message path."""
        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [{"from": "919876543210", "id": "wamid.M"}]}}]}
            ]
        }
        assert parse_statuses(payload) == []

    def test_malformed_envelope_returns_empty(self):
        for payload in (
            {},
            {"entry": []},
            {"entry": [{}]},
            {"entry": [{"changes": []}]},
            None,
        ):
            assert parse_statuses(payload or {}) == []

    def test_missing_timestamp_defaults_to_now(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.X",
                                        "status": "delivered",
                                        "recipient_id": "919876543210",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = parse_statuses(payload)
        # Allow a fudge factor of 5 seconds — test runtime.
        assert abs((events[0].timestamp - datetime.now(UTC)).total_seconds()) < 5

    def test_multiple_statuses_in_one_payload(self):
        """Meta occasionally batches multiple events in a single POST."""
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.A",
                                        "status": "delivered",
                                        "recipient_id": "919999999999",
                                        "timestamp": "1700000000",
                                    },
                                    {
                                        "id": "wamid.B",
                                        "status": "read",
                                        "recipient_id": "918888888888",
                                        "timestamp": "1700000050",
                                    },
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        events = parse_statuses(payload)
        assert [e.channel_message_id for e in events] == ["wamid.A", "wamid.B"]
        assert [e.status for e in events] == ["delivered", "read"]


# --- apply_meta_status forward-only state machine ----------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal AsyncSession that returns a single row from `execute()`
    and tracks commits."""

    def __init__(self, row):
        self.row = row
        self.commits = 0

    async def execute(self, _stmt):
        return _FakeResult(self.row)

    async def commit(self):
        self.commits += 1


def _make_message(
    *,
    status: CampaignMessageStatus,
    channel_message_id: str = "wamid.X",
    delivered_at=None,
    read_at=None,
    error=None,
) -> CampaignMessage:
    return CampaignMessage(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        channel_message_id=channel_message_id,
        status=status,
        error=error,
        sent_at=datetime(2026, 5, 1, tzinfo=UTC),
        delivered_at=delivered_at,
        read_at=read_at,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


class TestApplyMetaStatus:
    @pytest.mark.asyncio
    async def test_delivered_stamps_timestamp_and_advances_status(self):
        row = _make_message(status=CampaignMessageStatus.sent)
        session = _FakeSession(row)
        ts = datetime(2026, 5, 2, 10, 0, tzinfo=UTC)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="delivered",
            timestamp=ts,
        )
        assert updated is True
        assert row.status == CampaignMessageStatus.delivered
        assert row.delivered_at == ts
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_read_advances_past_delivered(self):
        row = _make_message(
            status=CampaignMessageStatus.delivered,
            delivered_at=datetime(2026, 5, 2, tzinfo=UTC),
        )
        session = _FakeSession(row)
        ts = datetime(2026, 5, 2, 11, 0, tzinfo=UTC)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="read",
            timestamp=ts,
        )
        assert updated is True
        assert row.status == CampaignMessageStatus.read
        assert row.read_at == ts
        # Delivered timestamp untouched.
        assert row.delivered_at == datetime(2026, 5, 2, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_forward_only_does_not_downgrade(self):
        """A stale `delivered` event arriving after `read` doesn't roll
        the status back."""
        row = _make_message(
            status=CampaignMessageStatus.read,
            read_at=datetime(2026, 5, 2, tzinfo=UTC),
            delivered_at=datetime(2026, 5, 2, tzinfo=UTC),
        )
        session = _FakeSession(row)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="delivered",
            timestamp=datetime(2026, 5, 3, tzinfo=UTC),
        )
        assert updated is False
        assert row.status == CampaignMessageStatus.read
        # Delivered timestamp was already set; no change.
        assert row.delivered_at == datetime(2026, 5, 2, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_failed_event_marks_failed_with_error(self):
        row = _make_message(status=CampaignMessageStatus.sent)
        session = _FakeSession(row)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="failed",
            timestamp=datetime(2026, 5, 2, tzinfo=UTC),
            error="Recipient not on WhatsApp",
        )
        assert updated is True
        assert row.status == CampaignMessageStatus.failed
        assert row.error == "Recipient not on WhatsApp"

    @pytest.mark.asyncio
    async def test_failed_is_terminal_against_late_delivered(self):
        """A `delivered` event after `failed` is ignored — failed is
        the terminal state."""
        row = _make_message(status=CampaignMessageStatus.failed, error="prior failure")
        session = _FakeSession(row)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="delivered",
            timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        )
        assert updated is False
        assert row.status == CampaignMessageStatus.failed

    @pytest.mark.asyncio
    async def test_meta_sent_is_noop(self):
        """Meta's `sent` status echoes what our dispatch already set;
        no DB write needed."""
        row = _make_message(status=CampaignMessageStatus.sent)
        session = _FakeSession(row)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.X",
            meta_status="sent",
            timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        )
        assert updated is False
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_unknown_channel_message_id_returns_false(self):
        """An outbound message that wasn't ours (e.g. manual reply from
        the inbox) doesn't have a CampaignMessage row — the helper
        returns False rather than raising."""
        session = _FakeSession(None)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="wamid.UNKNOWN",
            meta_status="delivered",
            timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        )
        assert updated is False

    @pytest.mark.asyncio
    async def test_empty_message_id_returns_false(self):
        session = _FakeSession(None)
        updated = await campaigns_service.apply_meta_status(
            session,
            channel_message_id="",
            meta_status="delivered",
            timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        )
        assert updated is False
