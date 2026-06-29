"""Pin tests for the Step-12 compliance pre-flight.

Exercises ``core.workflows.compliance.check_send`` directly with
seeded org / contact / settings rows. The send.* action handlers
delegate to this helper; testing it in isolation pins the gate
semantics + keeps the Send-handler test surface narrow.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import compliance
from src.app.core.workflows.compliance import (
    Allow,
    Defer,
    Skip,
    check_send,
    ensure_unsubscribe_link,
)


pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    contact_id: uuid.UUID | None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest_asyncio.fixture
async def org_with_settings(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_org_settings (id, org_id) "
            "VALUES (:id, :org_id)"
        ),
        {"id": str(uuid.uuid4()), "org_id": str(org_id)},
    )
    await test_db.commit()
    return org_id


async def _make_contact(
    test_db, *, org_id, email_opt_out: bool = False, wa_status: str = "never_contacted"
) -> uuid.UUID:
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts "
            "(id, org_id, full_name, email, email_opt_out, "
            " whatsapp_opt_in_status) "
            "VALUES (:id, :org_id, :name, :email, :opt_out, :wa)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "name": "Asha",
            "email": "asha@example.com",
            "opt_out": email_opt_out,
            "wa": wa_status,
        },
    )
    await test_db.commit()
    return contact_id


async def _set_compliance(test_db, *, org_id, **overrides):
    """Patch OrgSettings compliance columns. Supports any of the
    nine Step-12 fields as keyword args."""
    pairs = ", ".join(f"{k} = :{k}" for k in overrides.keys())
    await test_db.execute(
        sql_text(
            f"UPDATE tbl_org_settings SET {pairs} WHERE org_id = :org_id"
        ),
        {**overrides, "org_id": str(org_id)},
    )
    await test_db.commit()


# ---------------------------------------------------------------------------
# Opt-out checks
# ---------------------------------------------------------------------------


async def test_opt_out_email_blocks_marketing(test_db, org_with_settings):
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id, email_opt_out=True)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    # Test inside quiet hours by using a non-quiet timezone window;
    # we run at 12:00 UTC + Asia/Kolkata is 17:30 IST (outside default
    # 21:00–09:00). Default settings are loaded from the seeded row.
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Skip)
    assert decision.reason == "opt_out"


async def test_opt_out_whatsapp_blocks_wa_only(test_db, org_with_settings):
    """Channel-specific opt-out: WA-stop contact still receives email."""
    org_id = org_with_settings
    contact_id = await _make_contact(
        test_db, org_id=org_id, wa_status="opted_out"
    )
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

    wa_decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.whatsapp", "config": {}},
        recipient="+91xxx",
        channel="whatsapp",
        category="marketing",
        now=now,
    )
    assert isinstance(wa_decision, Skip)
    assert wa_decision.reason == "opt_out"

    email_decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(email_decision, Allow)


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


async def test_quiet_hours_defers_marketing(test_db, org_with_settings):
    """Default quiet hours = 21:00–09:00 Asia/Kolkata. 22:00 IST
    = 16:30 UTC — defer to 09:00 IST tomorrow = 03:30 UTC."""
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    # 22:00 IST on 2026-06-29 = 16:30 UTC on the same date.
    now = datetime(2026, 6, 29, 16, 30, tzinfo=timezone.utc)

    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Defer)
    assert decision.reason == "deferred_quiet_hours"
    # Expected: 09:00 IST tomorrow = 03:30 UTC on 2026-06-30.
    assert decision.until.astimezone(timezone.utc) == datetime(
        2026, 6, 30, 3, 30, tzinfo=timezone.utc
    )


async def test_quiet_hours_transactional_bypasses(test_db, org_with_settings):
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    now = datetime(2026, 6, 29, 16, 30, tzinfo=timezone.utc)

    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="transactional",
        now=now,
    )
    assert isinstance(decision, Allow)


async def test_quiet_hours_outside_window_allows(test_db, org_with_settings):
    """13:00 IST = 07:30 UTC. Outside the 21:00–09:00 IST window."""
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    now = datetime(2026, 6, 29, 7, 30, tzinfo=timezone.utc)

    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Allow)


async def test_quiet_hours_past_midnight_defers_to_today(
    test_db, org_with_settings
):
    """03:00 IST = 21:30 UTC PREVIOUS day. We're past midnight in
    IST → end (09:00 IST) is TODAY, not tomorrow."""
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    # 03:00 IST on 2026-06-30 = 21:30 UTC on 2026-06-29.
    now = datetime(2026, 6, 29, 21, 30, tzinfo=timezone.utc)

    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Defer)
    # Expected: 09:00 IST on 2026-06-30 = 03:30 UTC on 2026-06-30.
    assert decision.until.astimezone(timezone.utc) == datetime(
        2026, 6, 30, 3, 30, tzinfo=timezone.utc
    )


# ---------------------------------------------------------------------------
# Frequency cap
# ---------------------------------------------------------------------------


async def test_frequency_cap_zero_disables_check(test_db, org_with_settings):
    """Per-week + per-day cap of 0 means the gate doesn't block."""
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    await _set_compliance(
        test_db,
        org_id=org_id,
        frequency_cap_marketing_per_week=0,
        frequency_cap_marketing_per_day=0,
    )
    # Use a non-quiet time so the cap path is the only gate.
    now = datetime(2026, 6, 29, 7, 30, tzinfo=timezone.utc)
    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Allow)


# ---------------------------------------------------------------------------
# Allow path (no DB writes; quick return)
# ---------------------------------------------------------------------------


async def test_allow_path_for_clean_contact_outside_quiet_hours(
    test_db, org_with_settings
):
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    now = datetime(2026, 6, 29, 7, 30, tzinfo=timezone.utc)
    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="marketing",
        now=now,
    )
    assert isinstance(decision, Allow)


# ---------------------------------------------------------------------------
# Transactional bypass flags
# ---------------------------------------------------------------------------


async def test_transactional_with_bypass_disabled_still_gated(
    test_db, org_with_settings
):
    """Setting transactional_bypass_quiet_hours=False forces
    transactional sends through the quiet-hours gate too."""
    org_id = org_with_settings
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _FakeRun(org_id=org_id, contact_id=contact_id)
    await _set_compliance(
        test_db, org_id=org_id, transactional_bypass_quiet_hours=False
    )
    now = datetime(2026, 6, 29, 16, 30, tzinfo=timezone.utc)  # 22:00 IST

    decision = await check_send(
        test_db,
        run=run,
        node={"id": "n", "type": "send.email", "config": {}},
        recipient="asha@example.com",
        channel="email",
        category="transactional",
        now=now,
    )
    assert isinstance(decision, Defer)


# ---------------------------------------------------------------------------
# Unsubscribe footer auto-injection
# ---------------------------------------------------------------------------


async def test_ensure_unsubscribe_injects_footer_when_missing(
    test_db, org_with_settings
):
    body = "Hi Asha — check out our offer."
    new_body, injected = await ensure_unsubscribe_link(
        test_db,
        org_id=org_with_settings,
        category="marketing",
        channel="email",
        body=body,
    )
    assert injected is True
    assert "unsubscribe" in new_body.lower()


async def test_ensure_unsubscribe_skips_when_present(test_db, org_with_settings):
    body = "Hi Asha — to unsubscribe click here."
    new_body, injected = await ensure_unsubscribe_link(
        test_db,
        org_id=org_with_settings,
        category="marketing",
        channel="email",
        body=body,
    )
    assert injected is False
    assert new_body == body


async def test_ensure_unsubscribe_skips_for_non_email_channels(
    test_db, org_with_settings
):
    body = "Hi Asha"
    new_body, injected = await ensure_unsubscribe_link(
        test_db,
        org_id=org_with_settings,
        category="marketing",
        channel="whatsapp",
        body=body,
    )
    assert injected is False
    assert new_body == body


async def test_ensure_unsubscribe_skips_for_transactional_email(
    test_db, org_with_settings
):
    body = "Your invoice receipt"
    new_body, injected = await ensure_unsubscribe_link(
        test_db,
        org_id=org_with_settings,
        category="transactional",
        channel="email",
        body=body,
    )
    assert injected is False
    assert new_body == body
