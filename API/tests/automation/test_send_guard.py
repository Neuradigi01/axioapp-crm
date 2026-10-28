"""Pin tests for the Step-13 send-guard layer.

Covers the three checks + their composite:

  * DPDP suppression (per-channel opt-out)
  * Frequency cap (rolling 7-day marketing count per contact)
  * Quiet hours (org timezone + wrap-midnight aware)
  * Composite ``evaluate`` short-circuits on the first non-allow
    decision; transactional templates bypass everything.

The frequency-cap DAL goes through ``count_marketing_runs_for_contact``;
the cap test inserts real runs + asserts the count + the verdict.

Quiet-hours tests run with ``zoneinfo`` directly — no real wall
clock — so the verdict matrix is deterministic in CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.automation import send_guard
from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
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
            "name": "Demo Workspace",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


def _fake_org(
    *,
    org_id: uuid.UUID,
    quiet_start: time = time(21, 0),
    quiet_end: time = time(9, 0),
    tz: str = "Asia/Kolkata",
    cap_per_week: int = 3,
    cap_enabled: bool = True,
) -> SimpleNamespace:
    """In-memory org-shape used for tests that don't need the
    Organization ORM row — the send-guard reads attributes off
    ``org``, not a typed model, so a SimpleNamespace is plenty."""
    return SimpleNamespace(
        id=org_id,
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
        quiet_hours_timezone=tz,
        marketing_frequency_cap_per_week=cap_per_week,
        marketing_frequency_cap_enabled=cap_enabled,
    )


def _fake_template(category: TemplateCategory) -> SimpleNamespace:
    return SimpleNamespace(category=category, name="t")


def _fake_contact(
    *,
    whatsapp_status: str = "opted_in",
    email_opt_out: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        whatsapp_opt_in_status=whatsapp_status,
        email_opt_out=email_opt_out,
    )


async def _make_marketing_template(test_db, *, org_id) -> MessageTemplate:
    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name=f"Mkt-{uuid.uuid4().hex[:4]}",
        category=TemplateCategory.marketing,
        language="en",
        body_text="Hello",
        subject="Hello",
        variables=[],
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    test_db.add(template)
    await test_db.commit()
    await test_db.refresh(template)
    return template


async def _make_trigger(test_db, *, org_id, template_id) -> AutomationTrigger:
    trigger = AutomationTrigger(
        org_id=org_id,
        name=f"trg-{uuid.uuid4().hex[:6]}",
        enabled=True,
        event_type="lead.created",
        conditions={},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.email",
        recipient_resolver_config={},
    )
    test_db.add(trigger)
    await test_db.commit()
    await test_db.refresh(trigger)
    return trigger


async def _insert_marketing_run(
    test_db,
    *,
    org_id,
    trigger_id,
    contact_id,
    status: AutomationRunStatus,
    completed_at: datetime,
) -> AutomationRun:
    run = AutomationRun(
        org_id=org_id,
        trigger_id=trigger_id,
        event_id=f"event-{uuid.uuid4()}",
        event_payload={},
        contact_id=contact_id,
        status=status,
        scheduled_at=completed_at,
        dispatched_at=completed_at,
        completed_at=completed_at,
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# DPDP suppression
# ---------------------------------------------------------------------------


def test_dpdp_blocks_whatsapp_opted_out():
    contact = _fake_contact(whatsapp_status="opted_out")
    decision = send_guard.check_dpdp_suppression(channel="whatsapp", contact=contact)
    assert not decision.allow
    assert decision.skip_reason == "dpdp_suppressed"


def test_dpdp_blocks_email_opt_out():
    contact = _fake_contact(email_opt_out=True)
    decision = send_guard.check_dpdp_suppression(channel="email", contact=contact)
    assert not decision.allow
    assert decision.skip_reason == "dpdp_suppressed"


def test_dpdp_allows_opted_in_whatsapp():
    contact = _fake_contact(whatsapp_status="opted_in")
    decision = send_guard.check_dpdp_suppression(channel="whatsapp", contact=contact)
    assert decision.allow


# ---------------------------------------------------------------------------
# Frequency cap
# ---------------------------------------------------------------------------


async def test_frequency_cap_allows_within_limit(test_db, org_id):
    template = await _make_marketing_template(test_db, org_id=org_id)
    trigger = await _make_trigger(test_db, org_id=org_id, template_id=template.id)
    contact_id = uuid.uuid4()
    now = datetime.now(UTC)
    # Two previous sends in the last 7 days, cap=3 → still under.
    for _ in range(2):
        await _insert_marketing_run(
            test_db,
            org_id=org_id,
            trigger_id=trigger.id,
            contact_id=contact_id,
            status=AutomationRunStatus.sent,
            completed_at=now - timedelta(days=2),
        )

    org = _fake_org(org_id=org_id, cap_per_week=3, cap_enabled=True)
    decision = await send_guard.check_frequency_cap(
        test_db, org=org, contact_id=contact_id, now_utc=now
    )
    assert decision.allow


async def test_frequency_cap_blocks_past_limit(test_db, org_id):
    template = await _make_marketing_template(test_db, org_id=org_id)
    trigger = await _make_trigger(test_db, org_id=org_id, template_id=template.id)
    contact_id = uuid.uuid4()
    now = datetime.now(UTC)
    for _ in range(3):
        await _insert_marketing_run(
            test_db,
            org_id=org_id,
            trigger_id=trigger.id,
            contact_id=contact_id,
            status=AutomationRunStatus.sent,
            completed_at=now - timedelta(days=1),
        )

    org = _fake_org(org_id=org_id, cap_per_week=3, cap_enabled=True)
    decision = await send_guard.check_frequency_cap(
        test_db, org=org, contact_id=contact_id, now_utc=now
    )
    assert not decision.allow
    assert decision.skip_reason == "frequency_cap_exceeded"


async def test_frequency_cap_zero_blocks_all_marketing(test_db, org_id):
    org = _fake_org(org_id=org_id, cap_per_week=0, cap_enabled=True)
    decision = await send_guard.check_frequency_cap(
        test_db,
        org=org,
        contact_id=uuid.uuid4(),
        now_utc=datetime.now(UTC),
    )
    assert not decision.allow
    assert decision.skip_reason == "frequency_cap_exceeded"


async def test_frequency_cap_disabled_bypasses(test_db, org_id):
    org = _fake_org(org_id=org_id, cap_per_week=1, cap_enabled=False)
    decision = await send_guard.check_frequency_cap(
        test_db,
        org=org,
        contact_id=uuid.uuid4(),
        now_utc=datetime.now(UTC),
    )
    assert decision.allow


async def test_frequency_cap_only_counts_recent_window(test_db, org_id):
    """Marketing runs older than 7 days don't count toward the cap."""
    template = await _make_marketing_template(test_db, org_id=org_id)
    trigger = await _make_trigger(test_db, org_id=org_id, template_id=template.id)
    contact_id = uuid.uuid4()
    now = datetime.now(UTC)
    # 4 runs > 7 days ago — should NOT count.
    for _ in range(4):
        await _insert_marketing_run(
            test_db,
            org_id=org_id,
            trigger_id=trigger.id,
            contact_id=contact_id,
            status=AutomationRunStatus.sent,
            completed_at=now - timedelta(days=10),
        )
    org = _fake_org(org_id=org_id, cap_per_week=3, cap_enabled=True)
    decision = await send_guard.check_frequency_cap(
        test_db, org=org, contact_id=contact_id, now_utc=now
    )
    assert decision.allow


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


def test_quiet_hours_wrap_midnight_inside_window():
    """22:00 IST is inside the 21:00→09:00 quiet window — defer."""
    ist = ZoneInfo("Asia/Kolkata")
    now_local = datetime(2026, 6, 29, 22, 0, tzinfo=ist)
    now_utc = now_local.astimezone(UTC)
    org = _fake_org(
        org_id=uuid.uuid4(),
        quiet_start=time(21, 0),
        quiet_end=time(9, 0),
        tz="Asia/Kolkata",
    )
    decision = send_guard.check_quiet_hours(org=org, now_utc=now_utc)
    assert not decision.allow
    assert decision.defer_until is not None
    # The defer target must land at 09:00 the next IST day.
    defer_local = decision.defer_until.astimezone(ist)
    assert defer_local.hour == 9 and defer_local.minute == 0
    assert defer_local.date() == (now_local + timedelta(days=1)).date()


def test_quiet_hours_outside_window_allows():
    """12:00 IST is OUTSIDE the 21:00→09:00 window — allow."""
    ist = ZoneInfo("Asia/Kolkata")
    now_local = datetime(2026, 6, 29, 12, 0, tzinfo=ist)
    now_utc = now_local.astimezone(UTC)
    org = _fake_org(
        org_id=uuid.uuid4(),
        quiet_start=time(21, 0),
        quiet_end=time(9, 0),
        tz="Asia/Kolkata",
    )
    decision = send_guard.check_quiet_hours(org=org, now_utc=now_utc)
    assert decision.allow


def test_quiet_hours_respects_org_timezone():
    """A UTC-based org evaluates the same wall-clock window in UTC,
    not IST. 22:00 UTC is inside; 12:00 UTC is outside."""
    utc_tz = ZoneInfo("UTC")
    org = _fake_org(
        org_id=uuid.uuid4(),
        quiet_start=time(21, 0),
        quiet_end=time(9, 0),
        tz="UTC",
    )
    inside = datetime(2026, 6, 29, 22, 0, tzinfo=utc_tz)
    outside = datetime(2026, 6, 29, 12, 0, tzinfo=utc_tz)
    assert not send_guard.check_quiet_hours(org=org, now_utc=inside).allow
    assert send_guard.check_quiet_hours(org=org, now_utc=outside).allow


# ---------------------------------------------------------------------------
# Composite evaluate()
# ---------------------------------------------------------------------------


async def test_evaluate_transactional_bypasses_all_checks(test_db, org_id):
    """Transactional templates never go through any send-guard check —
    even with an opted-out contact + over-cap + quiet hours."""
    template = _fake_template(TemplateCategory.transactional)
    contact = _fake_contact(whatsapp_status="opted_out", email_opt_out=True)
    org = _fake_org(org_id=org_id, cap_per_week=0, cap_enabled=True)
    decision = await send_guard.evaluate(
        test_db,
        org=org,
        template=template,
        contact=contact,
        contact_id=uuid.uuid4(),
        channel="email",
        now_utc=datetime(2026, 6, 29, 22, 0, tzinfo=UTC),
    )
    assert decision.allow


async def test_evaluate_marketing_opted_out_blocks_first(test_db, org_id):
    """DPDP is the first check — verdict comes out as suppressed even
    if cap + quiet hours would also block."""
    template = _fake_template(TemplateCategory.marketing)
    contact = _fake_contact(email_opt_out=True)
    org = _fake_org(org_id=org_id, cap_per_week=0, cap_enabled=True)
    decision = await send_guard.evaluate(
        test_db,
        org=org,
        template=template,
        contact=contact,
        contact_id=uuid.uuid4(),
        channel="email",
        now_utc=datetime.now(UTC),
    )
    assert not decision.allow
    assert decision.skip_reason == "dpdp_suppressed"
