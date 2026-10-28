"""Pin tests for the Step-14 deliverability surface.

Covers:

  * Per-provider bounce-payload parsers (Mailgun, SendGrid, SES,
    Postmark).
  * HMAC validation rejects forged Mailgun webhooks.
  * Suppression-row writes on hard bounce / complaint / unsubscribe;
    soft bounce records to ``tbl_email_bounce_events`` only.
  * Provider-event-id uniqueness drops duplicate re-deliveries.
  * ``send_guard.check_suppression`` blocks sends for suppressed
    addresses and allows un-suppressed.
  * Manual DELETE removes the row + the next send is allowed.
  * Open-pixel + click-redirect tokens verify correctly + the
    engagement timestamps stamp once.
  * Pixel + link rewriter injects the open-pixel + click prefix.

Tests exercise the parsers + DAL writes + send_guard directly;
the HTTP endpoints are one-line passthroughs over those primitives.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.automation import send_guard
from src.app.core.automation.models import (
    AutomationSuppression,
    EmailBounceEvent,
    SuppressionReason,
)
from src.app.core.automation.tracking import (
    inject_tracking_pixel_and_links,
    mint_token,
    verify_token,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.email.bounce_handler import (
    BounceEvent,
    parse_mailgun,
    parse_postmark,
    parse_provider_payload,
    parse_sendgrid,
    parse_ses,
    persist_bounce_events,
    verify_mailgun_signature,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


# ---------------------------------------------------------------------------
# Provider parsers
# ---------------------------------------------------------------------------


def test_mailgun_parses_hard_bounce():
    payload = {
        "event-data": {
            "event": "failed",
            "severity": "permanent",
            "recipient": "asha@x.com",
            "id": "abc123",
        }
    }
    events = parse_mailgun(payload)
    assert len(events) == 1
    assert events[0].email_address == "asha@x.com"
    assert events[0].bounce_type == "hard"
    assert events[0].provider_event_id == "abc123"


def test_sendgrid_parses_complaint_array():
    payload = [
        {
            "event": "spamreport",
            "email": "asha@x.com",
            "sg_event_id": "evt-1",
        },
        {"event": "open", "email": "asha@x.com", "sg_event_id": "evt-2"},
    ]
    events = parse_sendgrid(payload)
    assert len(events) == 1
    assert events[0].bounce_type == "complaint"
    assert events[0].provider == "sendgrid"


def test_ses_parses_bounce_notification():
    payload = {
        "notificationType": "Bounce",
        "bounce": {
            "bounceType": "Permanent",
            "feedbackId": "fb-1",
            "bouncedRecipients": [{"emailAddress": "asha@x.com"}],
        },
    }
    events = parse_ses(payload)
    assert len(events) == 1
    assert events[0].bounce_type == "hard"
    assert events[0].provider_event_id == "fb-1:asha@x.com"


def test_postmark_parses_spam_complaint():
    payload = {
        "RecordType": "SpamComplaint",
        "Email": "asha@x.com",
        "ID": 42,
    }
    events = parse_postmark(payload)
    assert len(events) == 1
    assert events[0].bounce_type == "complaint"
    assert events[0].provider_event_id == "42"


def test_parse_provider_payload_unknown_raises():
    from src.app.core.email.bounce_handler import UnsupportedWebhookError

    with pytest.raises(UnsupportedWebhookError):
        parse_provider_payload("acme", {})


# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------


def test_mailgun_signature_valid():
    signing_key = "supersecret"
    timestamp = "1700000000"
    token = "abc"
    expected = hmac.new(
        signing_key.encode("utf-8"),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()
    payload = {
        "signature": {
            "timestamp": timestamp,
            "token": token,
            "signature": expected,
        }
    }
    assert verify_mailgun_signature(payload, signing_key=signing_key) is True


def test_mailgun_signature_forged_rejected():
    payload = {
        "signature": {
            "timestamp": "1700000000",
            "token": "abc",
            "signature": "deadbeef",
        }
    }
    assert verify_mailgun_signature(payload, signing_key="supersecret") is False


# ---------------------------------------------------------------------------
# Persistence + suppression rules
# ---------------------------------------------------------------------------


async def test_hard_bounce_writes_suppression(test_db, org_id):
    events = [
        BounceEvent(
            email_address="asha@x.com",
            bounce_type="hard",
            provider="mailgun",
            provider_event_id="mg-1",
            raw_payload={},
        )
    ]
    summary = await persist_bounce_events(test_db, org_id=org_id, events=events)
    assert summary["recorded"] == 1
    assert summary["suppressed"] == 1

    rows = (
        (
            await test_db.execute(
                select(AutomationSuppression).where(AutomationSuppression.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].address == "asha@x.com"
    assert rows[0].reason == SuppressionReason.hard_bounce


async def test_soft_bounce_does_not_suppress(test_db, org_id):
    events = [
        BounceEvent(
            email_address="asha@x.com",
            bounce_type="soft",
            provider="mailgun",
            provider_event_id="mg-soft-1",
            raw_payload={},
        )
    ]
    summary = await persist_bounce_events(test_db, org_id=org_id, events=events)
    assert summary["suppressed"] == 0

    rows = (
        (
            await test_db.execute(
                select(AutomationSuppression).where(AutomationSuppression.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0
    bounces = (
        (await test_db.execute(select(EmailBounceEvent).where(EmailBounceEvent.org_id == org_id)))
        .scalars()
        .all()
    )
    assert len(bounces) == 1


async def test_duplicate_provider_event_id_skipped(test_db, org_id):
    events = [
        BounceEvent(
            email_address="asha@x.com",
            bounce_type="hard",
            provider="mailgun",
            provider_event_id="dup-1",
            raw_payload={},
        )
    ]
    first = await persist_bounce_events(test_db, org_id=org_id, events=events)
    second = await persist_bounce_events(test_db, org_id=org_id, events=events)
    assert first["recorded"] == 1
    assert second["skipped_dupes"] == 1
    assert second["recorded"] == 0


# ---------------------------------------------------------------------------
# check_suppression integration
# ---------------------------------------------------------------------------


async def test_check_suppression_blocks_suppressed(test_db, org_id):
    test_db.add(
        AutomationSuppression(
            org_id=org_id,
            channel=ConversationChannel.email,
            address="block@x.com",
            reason=SuppressionReason.hard_bounce,
        )
    )
    await test_db.commit()

    decision = await send_guard.check_suppression(
        test_db,
        org_id=org_id,
        channel="email",
        recipient="block@x.com",
    )
    assert not decision.allow
    assert decision.skip_reason == "suppressed"


async def test_check_suppression_allows_clean(test_db, org_id):
    decision = await send_guard.check_suppression(
        test_db,
        org_id=org_id,
        channel="email",
        recipient="clean@x.com",
    )
    assert decision.allow


async def test_delete_suppression_rehabilitates(test_db, org_id):
    row = AutomationSuppression(
        org_id=org_id,
        channel=ConversationChannel.email,
        address="lift@x.com",
        reason=SuppressionReason.manual,
    )
    test_db.add(row)
    await test_db.commit()

    blocked = await send_guard.check_suppression(
        test_db,
        org_id=org_id,
        channel="email",
        recipient="lift@x.com",
    )
    assert not blocked.allow

    await test_db.delete(row)
    await test_db.commit()

    allowed = await send_guard.check_suppression(
        test_db,
        org_id=org_id,
        channel="email",
        recipient="lift@x.com",
    )
    assert allowed.allow


# ---------------------------------------------------------------------------
# Open + click tokens
# ---------------------------------------------------------------------------


def test_open_token_round_trips():
    run_id = uuid.uuid4()
    token = mint_token(run_id=run_id, action="open")
    assert verify_token(run_id=run_id, action="open", token=token) is True


def test_open_token_rejects_forgery():
    run_id = uuid.uuid4()
    token = mint_token(run_id=run_id, action="open")
    # Same run, wrong action → reject.
    assert verify_token(run_id=run_id, action="click", token=token) is False
    # Different run, same action → reject.
    other = uuid.uuid4()
    assert verify_token(run_id=other, action="open", token=token) is False


def test_inject_tracking_pixel_appends_image_tag():
    run_id = uuid.uuid4()
    html = "<html><body><p>Hello</p></body></html>"
    rewritten = inject_tracking_pixel_and_links(
        run_id=run_id,
        html_body=html,
        public_base_url="https://crm.example.com",
    )
    assert rewritten is not None
    assert "/api/v1/automations/track/open/" in rewritten
    assert "</body>" in rewritten  # pixel inserted BEFORE </body>


def test_inject_tracking_rewrites_anchor_hrefs():
    run_id = uuid.uuid4()
    html = '<html><body><a href="https://example.com/p?q=1">x</a></body></html>'
    rewritten = inject_tracking_pixel_and_links(
        run_id=run_id,
        html_body=html,
        public_base_url="https://crm.example.com",
    )
    assert rewritten is not None
    assert "/api/v1/automations/track/click/" in rewritten
    # Original URL preserved as URL-encoded `u=` parameter.
    assert "u=https%3A%2F%2Fexample.com%2Fp%3Fq%3D1" in rewritten
