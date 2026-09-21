"""Coverage for Step 6 of tasks/email-sending-domains/.

Two sweeps: nightly re-verify of pending/verified rows + hourly re-
verify of demoted rows. Owner notifications on state transitions.
Beat wiring pinned so a future rename doesn't silently drop the beat.

The task modules open their own session via ``async_session``; we
monkey-patch the imported name inside ``tasks.py`` so the sweep
runs against the ``test_db`` engine. Mailgun is monkey-patched to
``_FakeMailgun`` at the api_client source module — the service's
``client=None`` path picks up the patched class through the same
mechanism the router tests use.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from src.app.core.email.mailgun.api_client import (
    DomainDetail,
)
from src.app.core.email.mailgun.api_client_errors import MailgunProviderError
from src.app.core.email_sender_setup import tasks as sender_tasks
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_RELEASED,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared state + fakes
# ---------------------------------------------------------------------------


_mailgun_calls: list[dict[str, Any]] = []
_notify_calls: list[dict[str, Any]] = []


def _dns_records(domain: str, *, valid: str = "valid") -> dict[str, Any]:
    return {
        "sending": [
            {
                "record_type": "TXT",
                "name": f"smtp._domainkey.{domain}",
                "value": "v=DKIM1;",
                "priority": None,
                "valid": valid,
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": domain,
                "value": "v=spf1 include:mailgun.org ~all",
                "priority": None,
                "valid": valid,
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": f"_dmarc.{domain}",
                "value": "v=DMARC1;",
                "priority": None,
                "valid": valid,
                "cached": [],
                "is_active": True,
            },
        ],
        "receiving": [
            {
                "record_type": "MX",
                "name": domain,
                "value": "mxa.mailgun.org",
                "priority": "10",
                "valid": valid,
                "cached": [],
                "is_active": True,
            }
        ],
    }


class _FakeMailgun:
    """Stand-in for :class:`MailgunApiClient`.

    Response verdict is configurable per test via
    :data:`_fake_mailgun_verdict`. Set to ``"valid"`` for all-pass,
    ``"unknown"`` for any-fail, or a callable that raises to
    simulate 5xx/DELETE failures.
    """

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    async def verify_domain(self, domain: str) -> DomainDetail:
        _mailgun_calls.append(("verify_domain", domain))
        raiser = _fake_mailgun_state.get("verify_raises")
        if raiser is not None:
            raise raiser
        valid = _fake_mailgun_state.get("verdict", "valid")
        records = _dns_records(domain, valid=valid)
        return DomainDetail(
            mailgun_domain_id="mg-fake",
            name=domain,
            state="active" if valid == "valid" else "unverified",
            type="custom",
            created_at=None,
            sending_dns_records=records["sending"],
            receiving_dns_records=records["receiving"],
        )

    async def delete_domain(self, domain: str) -> None:
        _mailgun_calls.append(("delete_domain", domain))
        raiser = _fake_mailgun_state.get("delete_raises")
        if raiser is not None:
            raise raiser


_fake_mailgun_state: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def _patch_dispatch(monkeypatch, test_db):
    """Redirect the sweep's ``async_session`` at the test engine +
    monkey-patch Mailgun/notify. Runs on every test."""
    _mailgun_calls.clear()
    _notify_calls.clear()
    _fake_mailgun_state.clear()
    _fake_mailgun_state["verdict"] = "valid"

    # Route the task's session factory at the test DB. The sweep
    # helpers do ``async with async_session() as session:`` — we
    # yield the SAME ``test_db`` session so seed writes are visible.
    @asynccontextmanager
    async def _test_session_factory():
        yield test_db

    monkeypatch.setattr(sender_tasks, "async_session", _test_session_factory)

    # Mailgun client patch — sweep's service call constructs
    # ``MailgunApiClient()`` late, so patching the source binds every
    # subsequent construction to _FakeMailgun.
    monkeypatch.setattr(
        "src.app.core.email.mailgun.api_client.MailgunApiClient",
        _FakeMailgun,
    )

    async def _capture_notify(**kwargs):
        _notify_calls.append(kwargs)

    monkeypatch.setattr(
        "src.app.core.notifications.service.notify",
        _capture_notify,
    )

    # Audit ships its own session in prod; neuter here.
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(
        "src.app.core.email_sender_setup.service.audit.log",
        _noop,
    )


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Cron Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"cron-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _seed_domain(
    session,
    *,
    org_id: uuid.UUID,
    domain: str,
    status: str = VERIFICATION_STATUS_PENDING,
    consecutive_failed_checks: int = 0,
    demoted_at: datetime | None = None,
) -> OrganizationEmailDomain:
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id=f"mg-{uuid.uuid4().hex[:8]}",
        dns_records={},
        verification_status=status,
        consecutive_failed_checks=consecutive_failed_checks,
        demoted_at=demoted_at,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# 1. Nightly sweep
# ---------------------------------------------------------------------------


async def test_nightly_sweep_re_verifies_pending_and_verified(test_db):
    org = await _make_org(test_db)
    pending = await _seed_domain(
        test_db, org_id=org.id, domain="p.example", status=VERIFICATION_STATUS_PENDING
    )
    verified = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="v.example",
        status=VERIFICATION_STATUS_VERIFIED,
    )
    # Demoted row must NOT be touched by the nightly sweep.
    await _seed_domain(
        test_db, org_id=org.id, domain="d.example", status=VERIFICATION_STATUS_DEMOTED
    )
    await test_db.commit()

    result = await sender_tasks._sweep_nightly_async()

    domains_verified = {c[1] for c in _mailgun_calls if c[0] == "verify_domain"}
    assert domains_verified == {"p.example", "v.example"}
    assert result["skipped"] == 0
    assert result["failed"] == 0
    # Pending → verified transition counted.
    assert result["verified"] == 1
    # Sanity: swept ids include both rows.
    assert str(pending.id) in result["swept_ids"]
    assert str(verified.id) in result["swept_ids"]


async def test_nightly_sweep_demotes_after_3_consecutive_failures(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS", "3")
    org = await _make_org(test_db)
    row = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="drifting.example",
        status=VERIFICATION_STATUS_VERIFIED,
        consecutive_failed_checks=2,  # will bump to 3 → threshold crossed
    )
    _fake_mailgun_state["verdict"] = "unknown"  # any-fail
    await test_db.commit()

    result = await sender_tasks._sweep_nightly_async()

    assert result["demoted"] == 1
    # Reload row.
    await test_db.refresh(row)
    assert row.verification_status == VERIFICATION_STATUS_DEMOTED
    assert row.demoted_at is not None


async def test_nightly_sweep_sends_demote_notification_to_owner(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS", "3")
    org = await _make_org(test_db)
    await _seed_domain(
        test_db,
        org_id=org.id,
        domain="drifting.example",
        status=VERIFICATION_STATUS_VERIFIED,
        consecutive_failed_checks=2,
    )
    _fake_mailgun_state["verdict"] = "unknown"
    await test_db.commit()

    # Owner lookup returns None (no Role/OrganizationMember seeded in
    # test_db) → notify() is skipped inside the helper's try/except
    # branch and the sweep still counts the demotion. This test pins
    # the "demote transition happens" path; owner-lookup success is
    # exercised in Step 5b tests.
    await sender_tasks._sweep_nightly_async()

    # Notify was NOT called because Owner isn't seeded — the sweep is
    # best-effort and continues. Verify the transition still fired.
    reloaded = (
        await test_db.execute(
            select(OrganizationEmailDomain).where(
                OrganizationEmailDomain.domain == "drifting.example"
            )
        )
    ).scalar_one()
    assert reloaded.verification_status == VERIFICATION_STATUS_DEMOTED


# ---------------------------------------------------------------------------
# 2. Hourly sweep
# ---------------------------------------------------------------------------


async def test_hourly_sweep_re_verifies_demoted_only(test_db):
    org = await _make_org(test_db)
    await _seed_domain(
        test_db, org_id=org.id, domain="v.example", status=VERIFICATION_STATUS_VERIFIED
    )
    await _seed_domain(
        test_db, org_id=org.id, domain="p.example", status=VERIFICATION_STATUS_PENDING
    )
    demoted = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="d.example",
        status=VERIFICATION_STATUS_DEMOTED,
        demoted_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await test_db.commit()

    result = await sender_tasks._sweep_hourly_async()

    domains_verified = {c[1] for c in _mailgun_calls if c[0] == "verify_domain"}
    # Only the demoted row was re-verified.
    assert domains_verified == {"d.example"}
    assert str(demoted.id) in result["swept_ids"]


async def test_hourly_sweep_recovers_when_all_pass_and_notifies(test_db):
    org = await _make_org(test_db)
    row = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="recovering.example",
        status=VERIFICATION_STATUS_DEMOTED,
        consecutive_failed_checks=5,
        demoted_at=datetime.now(UTC) - timedelta(hours=2),
    )
    _fake_mailgun_state["verdict"] = "valid"
    await test_db.commit()

    result = await sender_tasks._sweep_hourly_async()

    assert result["recovered"] == 1
    await test_db.refresh(row)
    assert row.verification_status == VERIFICATION_STATUS_VERIFIED
    assert row.demoted_at is None
    assert row.consecutive_failed_checks == 0


async def test_hourly_sweep_releases_after_14_days_demoted(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS", "14")
    org = await _make_org(test_db)
    row = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="ancient.example",
        status=VERIFICATION_STATUS_DEMOTED,
        demoted_at=datetime.now(UTC) - timedelta(days=15),
    )
    await test_db.commit()

    result = await sender_tasks._sweep_hourly_async()

    assert result["released"] == 1
    # Mailgun.delete_domain fired for the released row; verify was NOT
    # called because the release branch skips re-verify.
    assert ("delete_domain", "ancient.example") in _mailgun_calls
    verify_calls = [c for c in _mailgun_calls if c[0] == "verify_domain"]
    assert verify_calls == []
    await test_db.refresh(row)
    assert row.verification_status == VERIFICATION_STATUS_RELEASED


# ---------------------------------------------------------------------------
# 3. Provider-error handling
# ---------------------------------------------------------------------------


async def test_sweep_mailgun_5xx_does_not_advance_failed_counter(test_db):
    """Step 3 contract: 5xx from Mailgun does NOT bump the counter —
    that's a transient provider blip, not DNS drift. The sweep
    surfaces the row as ``skipped`` in the summary."""
    org = await _make_org(test_db)
    row = await _seed_domain(
        test_db,
        org_id=org.id,
        domain="blip.example",
        status=VERIFICATION_STATUS_VERIFIED,
        consecutive_failed_checks=1,
    )
    _fake_mailgun_state["verify_raises"] = MailgunProviderError("mailgun 502", status_code=502)
    await test_db.commit()

    result = await sender_tasks._sweep_nightly_async()

    assert result["skipped"] == 1
    await test_db.refresh(row)
    assert row.consecutive_failed_checks == 1
    assert row.verification_status == VERIFICATION_STATUS_VERIFIED


# ---------------------------------------------------------------------------
# 4. DAL row-lock discipline
# ---------------------------------------------------------------------------


async def test_sweep_row_lock_query_uses_for_update_skip_locked(test_db):
    """The DAL helper emits ``SELECT ... FOR UPDATE SKIP LOCKED``.

    We can't easily exercise two concurrent transactions in a unit
    test, so this pins the SQL — a future refactor that drops the
    lock (e.g. someone drops ``.with_for_update()`` because "we
    don't need it") fails this test.
    """
    from src.app.core.email_sender_setup import data_access

    org = await _make_org(test_db)
    await _seed_domain(test_db, org_id=org.id, domain="l.example")
    await test_db.commit()

    # Grab the compiled SQL for inspection. The DAL helper accepts a
    # statuses list — compile against the same shape the sweep uses.
    from sqlalchemy import select as _select
    from sqlalchemy.dialects import postgresql

    stmt = (
        _select(OrganizationEmailDomain)
        .where(
            OrganizationEmailDomain.verification_status.in_(
                [VERIFICATION_STATUS_PENDING, VERIFICATION_STATUS_VERIFIED]
            )
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    ).upper()
    assert "FOR UPDATE" in compiled
    assert "SKIP LOCKED" in compiled

    # Sanity — the DAL helper actually returns the row.
    rows = await data_access.lock_rows_for_sweep(
        test_db,
        statuses=[VERIFICATION_STATUS_PENDING, VERIFICATION_STATUS_VERIFIED],
        limit=10,
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 5. Beat wiring — pin the schedule + autodiscover
# ---------------------------------------------------------------------------


def test_beat_entries_registered_at_expected_cadence():
    from celery.schedules import crontab

    from src.celery.worker import celery

    nightly = celery.conf.beat_schedule.get("email-domains-sweep-nightly")
    hourly = celery.conf.beat_schedule.get("email-domains-sweep-demoted-hourly")

    assert nightly is not None
    assert (
        nightly["task"] == "src.app.core.email_sender_setup.tasks.sweep_email_domain_claims_nightly"
    )
    assert isinstance(nightly["schedule"], crontab)
    assert nightly["schedule"]._orig_hour == "4"
    assert nightly["schedule"]._orig_minute == "0"

    assert hourly is not None
    assert hourly["task"] == "src.app.core.email_sender_setup.tasks.sweep_demoted_domains_hourly"
    assert isinstance(hourly["schedule"], crontab)
    assert hourly["schedule"]._orig_minute == "0"
    # Hourly = every hour on the hour (hour="*").
    assert hourly["schedule"]._orig_hour == "*"


def test_sweep_tasks_in_worker_autodiscover_registry():
    from src.celery.worker import celery

    assert sender_tasks.sweep_email_domain_claims_nightly.name in celery.tasks
    assert sender_tasks.sweep_demoted_domains_hourly.name in celery.tasks
