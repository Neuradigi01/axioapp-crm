"""Warmup-ladder evaluator.

``evaluate_warmup_for_row`` reads the 24h Redis counters for one
reputation row and decides whether to advance the row's
``warmup_stage`` to the next rung. The rule:

    delivered_24h + bounces_24h + complaints_24h >= stage_cap * earn_fraction
    AND complaint_rate < threshold
    AND bounce_rate < threshold
    AND row.reputation_state == 'ok'

Advance action: bump ``warmup_stage`` by 1, stamp
``warmup_stage_earned_at = now()``, zero ``warmup_stage_current_sent``,
notify Owner ``reputation.warmup_advanced``.

Row-lock via ``SELECT ... FOR UPDATE`` so two concurrent beat runs
don't double-advance a hot row.

Called from :mod:`.tasks` on the 4-hour beat.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation import config, counters
from src.app.core.email.reputation.models import (
    REPUTATION_STATE_OK,
    OrganizationEmailReputation,
)

logger = logging.getLogger(__name__)


async def evaluate_warmup_for_row(
    session: AsyncSession,
    *,
    row_id: uuid.UUID,
) -> bool:
    """Evaluate ONE reputation row for warmup advance. Returns True
    when the row advanced, False otherwise.

    Row-locked with ``FOR UPDATE`` so two concurrent evaluators can't
    both bump the stage. Caller commits.
    """
    stmt = (
        select(OrganizationEmailReputation)
        .where(OrganizationEmailReputation.id == row_id)
        .with_for_update()
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return False

    if row.reputation_state != REPUTATION_STATE_OK:
        # Don't advance a warned or blocked row — recovery is its own
        # path (see :mod:`.shed`).
        return False

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
    total_events = delivered + bounced + complained
    cap = config.stage_cap(row.warmup_stage)
    if total_events < int(cap * config.earn_fraction()):
        return False

    # Threshold guard — a row that just barely met the earn fraction
    # BUT has already crossed complaint/bounce thresholds must NOT
    # advance (the shed evaluator will fire on the same tick).
    if delivered > 0:
        if complained / delivered >= config.complaint_rate_threshold():
            return False
        if bounced / delivered >= config.bounce_rate_threshold():
            return False

    row.warmup_stage = row.warmup_stage + 1
    row.warmup_stage_earned_at = datetime.now(UTC)
    row.warmup_stage_current_sent = 0
    await session.flush()

    logger.info(
        "reputation.warmup: advanced org=%s envelope=%s domain=%s stage=%d",
        row.org_id,
        row.envelope_type,
        row.domain_id,
        row.warmup_stage,
    )

    # Late import to avoid a notifications-module load on cold-start
    # when no rows have advanced yet.
    from src.app.core.email.reputation.notifications import notify_owner

    await notify_owner(
        session,
        org_id=row.org_id,
        notification_type="reputation.warmup_advanced",
        title=f"Email warmup: advanced to stage {row.warmup_stage}",
        body=(
            f"Envelope {row.envelope_type} is now sending up to "
            f"{config.stage_cap(row.warmup_stage)} messages / day."
        ),
        payload={
            "envelope_type": row.envelope_type,
            "domain_id": str(row.domain_id) if row.domain_id else None,
            "warmup_stage": row.warmup_stage,
            "stage_cap": config.stage_cap(row.warmup_stage),
        },
    )
    return True


async def evaluate_warmup_all_rows(session: AsyncSession) -> int:
    """Advance every eligible ``ok`` row. Returns the count advanced.
    Called from the 4h Celery beat."""
    stmt = select(OrganizationEmailReputation.id).where(
        OrganizationEmailReputation.reputation_state == REPUTATION_STATE_OK
    )
    ids = list((await session.execute(stmt)).scalars().all())
    advanced = 0
    for row_id in ids:
        try:
            if await evaluate_warmup_for_row(session, row_id=row_id):
                advanced += 1
                await session.commit()
        except Exception:
            logger.exception("reputation.warmup: evaluate_warmup_for_row failed row=%s", row_id)
            await session.rollback()
    return advanced


__all__ = ["evaluate_warmup_all_rows", "evaluate_warmup_for_row"]
