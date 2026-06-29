"""Pin tests for the Step-12 time-based triggers.

Covers:

  * ``scan_birthdays`` returns only contacts whose ``(month, day)``
    matches the supplied date — and the year-stamped event_id makes
    re-runs in the same day idempotent.
  * ``scan_stale_leads`` returns only ``active`` leads inactive for
    30+ days; the first-stale-date stamped event_id keeps daily
    re-scans from refiring.
  * Seeders install the birthday + stale-lead templates + triggers
    per org and are idempotent.
  * Disabling either seeded trigger blocks subsequent dispatches.

Tests exercise the scheduler module directly; the Celery wrapper is
one-line ``asyncio.run``. No real workers required.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.automation import (
    seeds as automation_seeds,
    scheduler as automation_scheduler,
    tasks as automation_tasks,
)
from src.app.core.automation.dispatcher import dispatch_event
from src.app.core.automation.models import (
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.automation.service import match_triggers
from src.app.core.leads.models import Lead, LeadStatus
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo Workspace",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _install_seeds(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await automation_seeds.install_default_org_seeds(
            test_db, org_id=org_id
        )
        await test_db.commit()
        return result
    finally:
        reset_context(token)


async def _make_contact(
    test_db,
    *,
    org_id,
    dob: date | None = None,
    full_name: str = "Asha Mehta",
    email: str = "asha@example.com",
    phone: str = "+919876543210",
) -> uuid.UUID:
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, "
            "phone, email, date_of_birth) "
            "VALUES (:id, :org_id, :full_name, :phone, :email, :dob)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "dob": dob,
        },
    )
    await test_db.commit()
    return contact_id


async def _make_lead(
    test_db,
    *,
    org_id,
    contact_id: uuid.UUID,
    status: LeadStatus = LeadStatus.active,
    last_activity_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Lead:
    lead = Lead(
        org_id=org_id,
        contact_id=contact_id,
        status=status,
        pipeline_stage="qualified",
        source="manual",
        last_activity_at=last_activity_at,
    )
    test_db.add(lead)
    await test_db.commit()
    await test_db.refresh(lead)
    if created_at is not None:
        # Override the server-default ``now()`` for stale-since-creation
        # test cases.
        await test_db.execute(
            sql_text(
                "UPDATE tbl_leads SET created_at = :created_at "
                "WHERE id = :id"
            ),
            {"created_at": created_at, "id": str(lead.id)},
        )
        await test_db.commit()
        await test_db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Birthday scan
# ---------------------------------------------------------------------------


async def test_birthday_scan_finds_today_only(test_db, org_id):
    """Contacts whose date_of_birth matches today (month + day)
    surface in the scan; others don't."""
    today = date(2026, 6, 29)
    birthday_today = await _make_contact(
        test_db,
        org_id=org_id,
        dob=date(1991, 6, 29),
        full_name="Born Today",
        email="today@example.com",
        phone="+911",
    )
    birthday_tomorrow = await _make_contact(
        test_db,
        org_id=org_id,
        dob=date(1991, 6, 30),
        full_name="Born Tomorrow",
        email="tomorrow@example.com",
        phone="+912",
    )

    envelopes = await automation_scheduler.scan_birthdays(
        test_db, today=today
    )
    ids = {env["payload"]["contact_id"] for env in envelopes}
    assert str(birthday_today) in ids
    assert str(birthday_tomorrow) not in ids


async def test_birthday_scan_skips_no_birthday(test_db, org_id):
    """A contact with date_of_birth = NULL never surfaces."""
    today = date(2026, 6, 29)
    no_dob = await _make_contact(
        test_db,
        org_id=org_id,
        dob=None,
        full_name="No DOB",
        email="nodob@example.com",
        phone="+913",
    )

    envelopes = await automation_scheduler.scan_birthdays(
        test_db, today=today
    )
    ids = {env["payload"]["contact_id"] for env in envelopes}
    assert str(no_dob) not in ids


async def test_birthday_event_id_includes_year(test_db, org_id):
    """The event_id year-stamp keeps the dispatcher's uniqueness
    check from collapsing across years — same contact in 2026 vs
    2027 yields two distinct rows."""
    contact_id = await _make_contact(
        test_db, org_id=org_id, dob=date(1991, 6, 29)
    )

    envs_2026 = await automation_scheduler.scan_birthdays(
        test_db, today=date(2026, 6, 29)
    )
    envs_2027 = await automation_scheduler.scan_birthdays(
        test_db, today=date(2027, 6, 29)
    )
    target_2026 = next(
        e for e in envs_2026 if e["payload"]["contact_id"] == str(contact_id)
    )
    target_2027 = next(
        e for e in envs_2027 if e["payload"]["contact_id"] == str(contact_id)
    )
    assert target_2026["event_id"].endswith(":2026")
    assert target_2027["event_id"].endswith(":2027")
    assert target_2026["event_id"] != target_2027["event_id"]


# ---------------------------------------------------------------------------
# Stale-lead scan
# ---------------------------------------------------------------------------


async def test_stale_lead_scan_finds_30d_inactive(test_db, org_id):
    """An active lead with ``last_activity_at = now - 31 days``
    surfaces in the 30d staleness window."""
    now = datetime.now(timezone.utc)
    contact_id = await _make_contact(
        test_db,
        org_id=org_id,
        full_name="Cold",
        email="cold@example.com",
        phone="+914",
    )
    lead = await _make_lead(
        test_db,
        org_id=org_id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(days=31),
    )

    envelopes = await automation_scheduler.scan_stale_leads(
        test_db, now=now
    )
    ids = {env["payload"]["lead_id"] for env in envelopes}
    assert str(lead.id) in ids


async def test_stale_lead_scan_skips_won_lost(test_db, org_id):
    """Leads in ``won`` / ``lost`` never surface — closed deals
    don't need a still-interested nudge."""
    now = datetime.now(timezone.utc)
    far_back = now - timedelta(days=60)
    contact_won = await _make_contact(
        test_db,
        org_id=org_id,
        full_name="Won",
        email="won@example.com",
        phone="+915",
    )
    contact_lost = await _make_contact(
        test_db,
        org_id=org_id,
        full_name="Lost",
        email="lost@example.com",
        phone="+916",
    )
    won_lead = await _make_lead(
        test_db,
        org_id=org_id,
        contact_id=contact_won,
        status=LeadStatus.won,
        last_activity_at=far_back,
    )
    lost_lead = await _make_lead(
        test_db,
        org_id=org_id,
        contact_id=contact_lost,
        status=LeadStatus.lost,
        last_activity_at=far_back,
    )

    envelopes = await automation_scheduler.scan_stale_leads(
        test_db, now=now
    )
    ids = {env["payload"]["lead_id"] for env in envelopes}
    assert str(won_lead.id) not in ids
    assert str(lost_lead.id) not in ids


async def test_stale_lead_event_id_is_first_stale_date(test_db, org_id):
    """The event_id embeds the first-stale ISO date so daily
    re-scans of the same lead produce the same event_id — the
    dispatcher's uniqueness check then drops the duplicate."""
    base_activity = datetime(2026, 5, 1, tzinfo=timezone.utc)
    contact_id = await _make_contact(
        test_db,
        org_id=org_id,
        full_name="Persistent Cold",
        email="cold2@example.com",
        phone="+917",
    )
    lead = await _make_lead(
        test_db,
        org_id=org_id,
        contact_id=contact_id,
        last_activity_at=base_activity,
    )

    # Two scans on different days — same event_id both times.
    envs_day1 = await automation_scheduler.scan_stale_leads(
        test_db, now=datetime(2026, 6, 5, tzinfo=timezone.utc)
    )
    envs_day2 = await automation_scheduler.scan_stale_leads(
        test_db, now=datetime(2026, 6, 6, tzinfo=timezone.utc)
    )
    target_day1 = next(
        e for e in envs_day1 if e["payload"]["lead_id"] == str(lead.id)
    )
    target_day2 = next(
        e for e in envs_day2 if e["payload"]["lead_id"] == str(lead.id)
    )
    # last_activity_at + 30 days = 2026-05-31, so both envelopes
    # carry the same stamp.
    assert target_day1["event_id"] == target_day2["event_id"]
    assert target_day1["event_id"].endswith(":2026-05-31")


# ---------------------------------------------------------------------------
# Seed installation
# ---------------------------------------------------------------------------


async def test_seeders_idempotent(test_db, org_id):
    """Re-running install_default_org_seeds yields the same trigger
    + template ids for the two new time-based seeds."""
    first = await _install_seeds(test_db, org_id)
    second = await _install_seeds(test_db, org_id)
    assert first["contact_birthday_trigger_id"] == second[
        "contact_birthday_trigger_id"
    ]
    assert first["lead_stale_30d_trigger_id"] == second[
        "lead_stale_30d_trigger_id"
    ]

    rows = (
        await test_db.execute(
            select(AutomationTrigger).where(
                AutomationTrigger.org_id == org_id,
                AutomationTrigger.event_type.in_(
                    ("contact.birthday", "lead.stale_30d")
                ),
            )
        )
    ).scalars().all()
    assert len(rows) == 2
    by_event = {r.event_type: r for r in rows}
    assert by_event["contact.birthday"].channel.value == "whatsapp"
    assert by_event["contact.birthday"].recipient_resolver == (
        "contact.phone"
    )
    assert by_event["lead.stale_30d"].channel.value == "email"
    assert by_event["lead.stale_30d"].recipient_resolver == (
        "contact.email"
    )


# ---------------------------------------------------------------------------
# Disabled trigger blocks send
# ---------------------------------------------------------------------------


async def test_disabled_birthday_trigger_skips_send(test_db, org_id):
    """If the operator disables the seeded 'Contact Birthday'
    trigger, subsequent dispatches enrol no runs."""
    seeds_result = await _install_seeds(test_db, org_id)
    trigger_id = uuid.UUID(seeds_result["contact_birthday_trigger_id"])
    trigger = (
        await test_db.execute(
            select(AutomationTrigger).where(
                AutomationTrigger.id == trigger_id,
                AutomationTrigger.org_id == org_id,
            )
        )
    ).scalar_one()
    trigger.enabled = False
    await test_db.commit()

    matches = await match_triggers(
        test_db,
        org_id=org_id,
        event_type="contact.birthday",
        payload={"contact": {"phone": "+919876543210"}},
    )
    names = [m.name for m in matches]
    assert "Contact Birthday" not in names

    with patch.object(automation_tasks.deliver_run, "apply_async") as schedule:
        runs = await dispatch_event(
            test_db,
            org_id=org_id,
            event_type="contact.birthday",
            payload={
                "contact_id": str(uuid.uuid4()),
                "contact": {
                    "full_name": "Asha Mehta",
                    "phone": "+919876543210",
                },
            },
            event_id=f"contact_birthday:{uuid.uuid4()}:2026",
        )

    assert runs == []
    assert not schedule.called
