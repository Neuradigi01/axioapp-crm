"""Coverage for Step 5 of tasks/email-endpoint-abstraction/.

Nightly orphan-endpoint sweeper. Verifies:

  * Orphan endpoints (no details row + created_at > 24h ago) get
    soft-deleted with ``deactivation_reason='orphan_sweeper'``.
  * Young orphans (< 24h) are left alone.
  * Endpoints with an intact details row are NEVER touched.
  * OAuth-mailbox endpoints whose backing ``tbl_email_accounts`` is
    ``disconnected`` for > 7d get soft-deleted with
    ``deactivation_reason='oauth_account_disconnected'``.
  * OAuth endpoints with a recently-disconnected account (< 7d) are
    left alone (grace window respected).
  * OAuth endpoints with a live account are never touched.
  * The task returns a summary dict with the expected keys.
  * Beat entry is registered at 03:15 UTC and the task appears in
    the Celery worker registry.

Wraps ``_sweep_orphan_endpoints_async`` (not the Celery-task shim) so
tests run inside the ``test_db`` session's engine without spinning up
a real worker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.channel_endpoints.tasks import (
    _OAUTH_DISCONNECTED_GRACE_DAYS,
    _ORPHAN_MIN_AGE_HOURS,
    _sweep_orphan_endpoints_async,
    sweep_orphan_endpoints,
)
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, slug: str = "s5") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_orphan_endpoint(
    session, *, org_id: uuid.UUID, age_hours: int, label: str = "orphan@ex.com"
) -> ChannelEndpoint:
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="smtp_reply_capture",
        label=label,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    session.add(endpoint)
    await session.flush()
    return endpoint


async def _make_healthy_endpoint(
    session, *, org_id: uuid.UUID, label: str = "healthy@ex.com"
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="smtp_reply_capture",
        label=label,
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        reply_token=f"rt-{uuid.uuid4().hex[:12]}",
    )
    session.add(details)
    await session.flush()
    return endpoint, details


async def _make_oauth_endpoint(
    session,
    *,
    org_id: uuid.UUID,
    sync_state: EmailAccountSyncState = EmailAccountSyncState.live,
    disconnected_at: datetime | None = None,
    label: str = "oauth@ex.com",
) -> tuple[ChannelEndpoint, EmailAccount]:
    account = EmailAccount(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        provider=EmailAccountProvider.gmail,
        external_account_id=label,
        email_address=label,
        display_name="OAuth Cust",
        access_token_enc="enc",
        refresh_token_enc="enc",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes_granted=[],
        sync_state=sync_state,
        daily_sent_count=0,
        daily_sent_reset_at=datetime.now(UTC),
        connected_at=datetime.now(UTC) - timedelta(days=30),
        disconnected_at=disconnected_at,
    )
    session.add(account)
    await session.flush()

    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="oauth_mailbox",
        label=label,
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        oauth_account_id=account.id,
    )
    session.add(details)
    await session.flush()
    return endpoint, account


async def _refresh(session, endpoint: ChannelEndpoint) -> ChannelEndpoint:
    await session.refresh(endpoint)
    return endpoint


# ---------------------------------------------------------------------------
# 1. Orphan-endpoint pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweeper_soft_deletes_orphan_older_than_24h(test_db):
    org = await _make_org(test_db, "orphan-old")
    orphan = await _make_orphan_endpoint(
        test_db, org_id=org.id, age_hours=_ORPHAN_MIN_AGE_HOURS + 1
    )
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert result["orphan_swept"] == 1
    assert str(orphan.id) in result["swept_ids"]

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == orphan.id)
        )
    ).scalar_one()
    assert reloaded.is_active is False
    assert reloaded.deactivated_at is not None
    assert reloaded.deactivation_reason == "orphan_sweeper"


@pytest.mark.asyncio
async def test_sweeper_leaves_young_orphan_alone(test_db):
    org = await _make_org(test_db, "orphan-young")
    orphan = await _make_orphan_endpoint(
        test_db, org_id=org.id, age_hours=_ORPHAN_MIN_AGE_HOURS - 1
    )
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert result["orphan_swept"] == 0

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == orphan.id)
        )
    ).scalar_one()
    assert reloaded.is_active is True


@pytest.mark.asyncio
async def test_sweeper_never_touches_healthy_endpoint(test_db):
    org = await _make_org(test_db, "healthy")
    healthy, _ = await _make_healthy_endpoint(test_db, org_id=org.id)
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert str(healthy.id) not in result["swept_ids"]

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == healthy.id)
        )
    ).scalar_one()
    assert reloaded.is_active is True


# ---------------------------------------------------------------------------
# 2. OAuth-disconnected pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweeper_soft_deletes_endpoint_for_disconnected_oauth_over_7d(test_db):
    org = await _make_org(test_db, "oauth-old")
    endpoint, _account = await _make_oauth_endpoint(
        test_db,
        org_id=org.id,
        sync_state=EmailAccountSyncState.disconnected,
        disconnected_at=datetime.now(UTC)
        - timedelta(days=_OAUTH_DISCONNECTED_GRACE_DAYS + 1),
    )
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert result["oauth_swept"] == 1

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == endpoint.id)
        )
    ).scalar_one()
    assert reloaded.is_active is False
    assert reloaded.deactivation_reason == "oauth_account_disconnected"


@pytest.mark.asyncio
async def test_sweeper_respects_7d_grace_for_recently_disconnected(test_db):
    org = await _make_org(test_db, "oauth-recent")
    endpoint, _account = await _make_oauth_endpoint(
        test_db,
        org_id=org.id,
        sync_state=EmailAccountSyncState.disconnected,
        disconnected_at=datetime.now(UTC) - timedelta(days=1),
    )
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert result["oauth_swept"] == 0

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == endpoint.id)
        )
    ).scalar_one()
    assert reloaded.is_active is True


@pytest.mark.asyncio
async def test_sweeper_never_touches_live_oauth_endpoint(test_db):
    org = await _make_org(test_db, "oauth-live")
    endpoint, _account = await _make_oauth_endpoint(
        test_db, org_id=org.id, sync_state=EmailAccountSyncState.live
    )
    await test_db.commit()

    result = await _sweep_orphan_endpoints_async()
    assert result["oauth_swept"] == 0

    reloaded = (
        await test_db.execute(
            select(ChannelEndpoint).where(ChannelEndpoint.id == endpoint.id)
        )
    ).scalar_one()
    assert reloaded.is_active is True


# ---------------------------------------------------------------------------
# 3. Summary dict shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweeper_returns_expected_summary_keys(test_db):
    result = await _sweep_orphan_endpoints_async()
    assert set(result.keys()) == {
        "orphan_swept",
        "oauth_swept",
        "failed",
        "swept_ids",
        "at",
    }
    assert isinstance(result["swept_ids"], list)


# ---------------------------------------------------------------------------
# 4. Wiring — beat entry + autodiscover
# ---------------------------------------------------------------------------


def test_beat_entry_registered_at_0315_utc():
    from celery.schedules import crontab

    from src.celery.worker import celery

    entry = celery.conf.beat_schedule.get(
        "channel-endpoints-sweep-orphans-nightly"
    )
    assert entry is not None, "beat entry not registered"
    assert (
        entry["task"]
        == "src.app.core.channel_endpoints.tasks.sweep_orphan_endpoints"
    )
    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    # crontab stores minute + hour as sets when parsing single-value strings.
    assert schedule._orig_minute == "15"
    assert schedule._orig_hour == "3"


def test_task_in_worker_autodiscover_registry():
    from src.celery.worker import celery

    assert sweep_orphan_endpoints.name in celery.tasks
