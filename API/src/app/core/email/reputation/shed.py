"""Reputation-shed evaluator + auto-recovery.

Two entry points:

  * :func:`evaluate_shed_for_row` — decides whether a row breached
    the complaint-rate or bounce-rate threshold and, if so, applies
    the shed action (state=``blocked``, ``blocked_until = now() +
    cooldown_hours``, warmup stage back to 0) + notifies Owner. Also
    covers the warning-zone transition (state=``warned`` at 80% of
    threshold).
  * :func:`sweep_blocked_until_expiry` — flips rows whose
    ``blocked_until`` has passed back to ``ok``. Cheap catch-net
    scheduled hourly.

Thresholds + cooldown come from :mod:`.config` so an Owner can
retune without a code change. The event-floor guard
(``EMAIL_REPUTATION_MIN_EVENTS``) prevents a single complaint on a
10-message day from tripping the cascade.

Row-locked via ``SELECT ... FOR UPDATE`` — the 4h beat can race with
the events webhook path both touching the same row (webhook bumps
counter; beat reads + writes state). ``FOR UPDATE`` serialises the
state write.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation import config, counters
from src.app.core.email.reputation.models import (
    REPUTATION_STATE_BLOCKED,
    REPUTATION_STATE_OK,
    REPUTATION_STATE_WARNED,
    OrganizationEmailReputation,
)
from src.app.core.email.reputation.notifications import notify_owner

logger = logging.getLogger(__name__)


async def _read_24h_events(row: OrganizationEmailReputation) -> tuple[int, int, int]:
    """Return ``(delivered, bounced, complained)`` from Redis."""
    delivered = await counters.sum_last_24h(
        org_id=row.org_id,
        envelope=row.envelope_type,
        domain_id=row.domain_id,
        event="delivered",
    )
    bounced = await counters.sum_last_24h(
        org_id=row.org_id,
        envelope=row.envelope_type,
        domain_id=row.domain_id,
        event="bounced",
    )
    complained = await counters.sum_last_24h(
        org_id=row.org_id,
        envelope=row.envelope_type,
        domain_id=row.domain_id,
        event="complained",
    )
    return delivered, bounced, complained


async def evaluate_shed_for_row(
    session: AsyncSession,
    *,
    row_id: uuid.UUID,
) -> str | None:
    """Evaluate ONE reputation row for shed.

    Return values (also written to ``row.reputation_state``):

      * ``'blocked'`` — a hard threshold breached; state flipped +
        Owner notified; warmup stage reset to 0.
      * ``'warned'`` — a rate crossed the 80% warning zone; Owner
        notified once per transition (idempotent — a row already in
        ``warned`` doesn't re-notify unless it clears + breaches again).
      * ``None`` — no transition.

    Caller commits after evaluating multiple rows.
    """
    stmt = (
        select(OrganizationEmailReputation)
        .where(OrganizationEmailReputation.id == row_id)
        .with_for_update()
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    if row.reputation_state == REPUTATION_STATE_BLOCKED:
        # Recovery is the sweeper's job — don't double-fire here.
        return None

    delivered, bounced, complained = await _read_24h_events(row)
    if delivered < config.event_floor():
        # Below floor — ratios are meaningless. Drop the row back to
        # ``ok`` if it was ``warned`` (the volume that triggered the
        # warning is aging out of the 24h window).
        if row.reputation_state == REPUTATION_STATE_WARNED:
            row.reputation_state = REPUTATION_STATE_OK
            await session.flush()
        return None

    complaint_rate = complained / delivered
    bounce_rate = bounced / delivered
    ct = config.complaint_rate_threshold()
    bt = config.bounce_rate_threshold()
    wf = config.warning_zone_fraction()

    # Hard shed — either rate over threshold.
    if complaint_rate >= ct or bounce_rate >= bt:
        cooldown_hours = config.breach_cooldown_hours()
        row.reputation_state = REPUTATION_STATE_BLOCKED
        row.blocked_until = datetime.now(UTC) + timedelta(hours=cooldown_hours)
        row.warmup_stage = 0
        row.warmup_stage_current_sent = 0
        await session.flush()
        logger.warning(
            "reputation.shed: BLOCKED org=%s envelope=%s domain=%s "
            "complaint_rate=%.4f bounce_rate=%.4f",
            row.org_id,
            row.envelope_type,
            row.domain_id,
            complaint_rate,
            bounce_rate,
        )
        which = "complaint" if complaint_rate >= ct else "bounce"
        await notify_owner(
            session,
            org_id=row.org_id,
            notification_type="reputation.blocked",
            title="Email reputation shed — sending paused",
            body=(
                f"{row.envelope_type}: {which} rate breached "
                f"({complaint_rate * 100:.2f}% complaints, "
                f"{bounce_rate * 100:.2f}% bounces over "
                f"{delivered} delivered in 24h). Sending resumes at "
                f"{row.blocked_until.isoformat()}."
            ),
            payload={
                "envelope_type": row.envelope_type,
                "domain_id": str(row.domain_id) if row.domain_id else None,
                "complaint_rate": complaint_rate,
                "bounce_rate": bounce_rate,
                "delivered_24h": delivered,
                "blocked_until": row.blocked_until.isoformat(),
                "which_breach": which,
            },
        )
        return REPUTATION_STATE_BLOCKED

    # Warning zone — either rate crossed 80% of its threshold.
    if complaint_rate >= ct * wf or bounce_rate >= bt * wf:
        if row.reputation_state == REPUTATION_STATE_WARNED:
            # Already warned; don't re-notify (state stays sticky
            # until the 24h window clears).
            return None
        row.reputation_state = REPUTATION_STATE_WARNED
        await session.flush()
        which = "complaint" if complaint_rate >= ct * wf else "bounce"
        await notify_owner(
            session,
            org_id=row.org_id,
            notification_type="reputation.warning",
            title="Email reputation nearing threshold",
            body=(
                f"{row.envelope_type}: {which} rate at "
                f"{max(complaint_rate, bounce_rate) * 100:.2f}% — approaching "
                f"the {(ct if which == 'complaint' else bt) * 100:.2f}% "
                "shed threshold. Consider pausing large sends."
            ),
            payload={
                "envelope_type": row.envelope_type,
                "domain_id": str(row.domain_id) if row.domain_id else None,
                "complaint_rate": complaint_rate,
                "bounce_rate": bounce_rate,
                "delivered_24h": delivered,
                "which_zone": which,
            },
        )
        return REPUTATION_STATE_WARNED

    # Both rates back under the warning zone → drop out of warned.
    if row.reputation_state == REPUTATION_STATE_WARNED:
        row.reputation_state = REPUTATION_STATE_OK
        await session.flush()
    return None


async def evaluate_shed_all_rows(session: AsyncSession) -> dict[str, int]:
    """Evaluate every reputation row. Returns ``{blocked: N, warned: N}``.
    Called from the 4h Celery beat."""
    stmt = select(OrganizationEmailReputation.id)
    ids = list((await session.execute(stmt)).scalars().all())
    counts = {"blocked": 0, "warned": 0}
    for row_id in ids:
        try:
            verdict = await evaluate_shed_for_row(session, row_id=row_id)
            if verdict == REPUTATION_STATE_BLOCKED:
                counts["blocked"] += 1
            elif verdict == REPUTATION_STATE_WARNED:
                counts["warned"] += 1
            await session.commit()
        except Exception:
            logger.exception("reputation.shed: evaluate_shed_for_row failed row=%s", row_id)
            await session.rollback()
    return counts


async def sweep_blocked_until_expiry(session: AsyncSession) -> int:
    """Flip rows whose ``blocked_until`` has passed back to ``ok`` +
    notify Owner. Called from the hourly Celery beat.

    Returns the count of rows recovered.
    """
    now = datetime.now(UTC)
    stmt = (
        select(OrganizationEmailReputation)
        .where(OrganizationEmailReputation.reputation_state == REPUTATION_STATE_BLOCKED)
        .where(OrganizationEmailReputation.blocked_until <= now)
        .with_for_update()
    )
    rows = list((await session.execute(stmt)).scalars().all())
    recovered = 0
    for row in rows:
        row.reputation_state = REPUTATION_STATE_OK
        row.blocked_until = None
        await session.flush()
        await notify_owner(
            session,
            org_id=row.org_id,
            notification_type="reputation.recovered",
            title="Email reputation recovered — sending resumed",
            body=(
                f"{row.envelope_type}: cooldown elapsed. Warmup restarts "
                "at stage 0 — cap will re-grow through the ladder as "
                "clean deliveries accumulate."
            ),
            payload={
                "envelope_type": row.envelope_type,
                "domain_id": str(row.domain_id) if row.domain_id else None,
                "warmup_stage": row.warmup_stage,
            },
        )
        recovered += 1
        await session.commit()
    return recovered


__all__ = [
    "evaluate_shed_all_rows",
    "evaluate_shed_for_row",
    "sweep_blocked_until_expiry",
]
