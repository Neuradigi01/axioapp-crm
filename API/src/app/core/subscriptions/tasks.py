"""Celery tasks for usage-counter housekeeping.

Two tasks, two cadences:

  - `rollover_period_counters` runs hourly (Celery Beat). For each
    active subscription whose `current_period_end` has passed, it
    advances the subscription's billing window forward one cycle
    (monthly or annual) and inserts fresh zeroed `monthly` counter
    rows for the new window. Idempotent: if the rollover task missed
    one or more boundaries (Celery beat outage), the loop catches up
    by advancing the subscription until `current_period_end > now()`.

  - `reset_daily_counters` runs at midnight UTC. For every active
    subscription, it inserts a fresh zeroed row for each `daily`
    resource (today `api_calls_per_day`) so the increment hot path
    has a row ready and avoids a thundering-herd insert at the first
    request of the day.

Both wrap their async work in `asyncio.run(...)` per the project's
Celery convention (see `src/celery/worker.py` for the engine reset
hooks that keep this safe across tasks).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

log = logging.getLogger(__name__)


# Cycle length used when advancing a subscription's billing window.
_CYCLE_LENGTHS: dict[str, timedelta] = {
    "monthly": timedelta(days=30),
    "annual": timedelta(days=365),
}


@shared_task(name="src.app.core.subscriptions.tasks.rollover_period_counters")
def rollover_period_counters() -> dict[str, Any]:
    """Hourly beat task — advance any subscription whose period has elapsed.

    Returns a summary dict for observability (`{advanced: N,
    counters_inserted: M}`). Celery itself does not act on it.
    """
    return asyncio.run(_rollover_period_counters_async())


async def _rollover_period_counters_async() -> dict[str, Any]:
    # Imports inside the body so importing `tasks.py` from FastAPI
    # bootstrap does not force the worker-only async-engine cost.
    from sqlalchemy import select

    from src.app.core.subscriptions.models import Subscription
    from src.app.core.subscriptions.usage_service import reset_monthly_counters
    from src.app.shared.db import async_session

    now = datetime.now(tz=UTC)
    advanced = 0
    counters_inserted = 0

    async with async_session() as session:
        # Beat has no tenant context; the auto-org-filter listener is a
        # no-op when `RequestContext.org_id is None`, so this plain SELECT
        # sees every org's row.
        rows = (
            (
                await session.execute(
                    select(Subscription).where(
                        Subscription.current_period_end <= now,
                        Subscription.status.in_(("trialing", "active")),
                    )
                )
            )
            .scalars()
            .all()
        )

        for sub in rows:
            cycle = _CYCLE_LENGTHS.get(sub.billing_cycle)
            if cycle is None:
                log.warning(
                    "skipping subscription %s with unknown billing_cycle %r",
                    sub.id,
                    sub.billing_cycle,
                )
                continue

            # Catch-up: if beat was down for multiple boundaries, advance
            # the subscription past every elapsed window before opening
            # the new counter rows.
            new_start = sub.current_period_end
            new_end = new_start + cycle
            while new_end <= now:
                new_start = new_end
                new_end = new_start + cycle

            sub.current_period_start = new_start
            sub.current_period_end = new_end
            counters_inserted += await reset_monthly_counters(
                session, sub.org_id, new_start, new_end
            )
            advanced += 1

        await session.commit()

    log.info(
        "rollover_period_counters advanced=%d counters_inserted=%d",
        advanced,
        counters_inserted,
    )
    return {"advanced": advanced, "counters_inserted": counters_inserted}


@shared_task(name="src.app.core.subscriptions.tasks.reset_daily_counters")
def reset_daily_counters() -> dict[str, Any]:
    """Midnight-UTC beat task — open the new day's `daily` counter rows.

    Idempotent. Returns a summary dict (`{orgs_processed: N,
    counters_inserted: M}`).
    """
    return asyncio.run(_reset_daily_counters_async())


async def _reset_daily_counters_async() -> dict[str, Any]:
    from sqlalchemy import select

    from src.app.core.subscriptions.models import ACTIVE_STATUSES, Subscription
    from src.app.core.subscriptions.usage_service import (
        _utc_day_bounds,
        reset_daily_counter_rows,
    )
    from src.app.shared.db import async_session

    start, end = _utc_day_bounds()
    orgs_processed = 0
    counters_inserted = 0

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Subscription.org_id).where(Subscription.status.in_(ACTIVE_STATUSES))
                )
            )
            .scalars()
            .all()
        )

        for org_id in rows:
            counters_inserted += await reset_daily_counter_rows(session, org_id, start, end)
            orgs_processed += 1

        await session.commit()

    log.info(
        "reset_daily_counters orgs_processed=%d counters_inserted=%d",
        orgs_processed,
        counters_inserted,
    )
    return {"orgs_processed": orgs_processed, "counters_inserted": counters_inserted}


# ---------------------------------------------------------------------------
# Step 6 — trial lifecycle advance
# ---------------------------------------------------------------------------


@shared_task(name="src.app.core.subscriptions.tasks.advance_trial_lifecycle")
def advance_trial_lifecycle() -> dict[str, Any]:
    """Hourly beat task — advance trial / read_only / archived states.

    Combines two passes:
      1. `fire_due_reminders` — queues `trial_ending_soon` emails for
         subs whose `trial_ends_at` is within 3 days and that have
         not been notified yet (dedup via
         `subscriptions.reminders_sent`).
      2. `scan_and_transition_due` — applies any due state transition
         (`trialing → read_only`, `read_only → archived`,
         `archived → row deleted`) with conditional UPDATEs that abort
         silently on a concurrent paid upgrade.

    Returns the summary dict so Celery's task-result store carries the
    last sweep's counts for observability.
    """
    return asyncio.run(_advance_trial_lifecycle_async())


async def _advance_trial_lifecycle_async() -> dict[str, Any]:
    from src.app.core.subscriptions.lifecycle import (
        fire_due_reminders,
        scan_and_transition_due,
    )
    from src.app.shared.db import async_session

    async with async_session() as session:
        reminders_fired = await fire_due_reminders(session)
        summary = await scan_and_transition_due(session)
        await session.commit()

    result = {**summary, "reminders_fired": reminders_fired}
    log.info("advance_trial_lifecycle %s", result)
    return result
