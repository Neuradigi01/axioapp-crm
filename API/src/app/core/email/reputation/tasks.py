"""Celery tasks for the reputation-warmup track.

Three tasks driven by three beat entries in
:mod:`src.celery.celery_config`:

  * :func:`evaluate_warmup_and_shed_4h` — every 4h. Sweeps every row
    once for warmup advance + shed evaluation. Two passes serially:
    shed first (a breach might have happened between beats and we
    don't want the same tick to advance a row that's about to be
    blocked), warmup second.
  * :func:`check_blocked_until_expiry_hourly` — every hour on the
    hour. Flips ``blocked`` rows past their cooldown back to ``ok`` +
    notifies Owner.
  * :func:`trim_reputation_buckets_hourly` — every hour at :15. Redis
    TTL already expires buckets; this catch-net exists per Step 2's
    counter module for hypothetical rogue writes without TTL.
"""

from __future__ import annotations

import asyncio
import logging

from src.app.core.email.reputation import counters, shed, warmup
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="src.app.core.email.reputation.tasks.evaluate_warmup_and_shed_4h",
    bind=True,
    max_retries=0,  # Beat re-fires every 4h; retry inside would double-fire.
    acks_late=True,
)
def evaluate_warmup_and_shed_4h(self) -> dict[str, int]:
    """4h Celery beat entry. Shed pass first (so a breach doesn't
    inadvertently earn a stage advance in the same tick), then
    warmup. Returns a summary dict for beat logs."""
    return asyncio.run(_run_evaluators())


async def _run_evaluators() -> dict[str, int]:
    async with async_session() as session:
        shed_counts = await shed.evaluate_shed_all_rows(session)
    async with async_session() as session:
        advanced = await warmup.evaluate_warmup_all_rows(session)
    summary = {
        "blocked": shed_counts.get("blocked", 0),
        "warned": shed_counts.get("warned", 0),
        "advanced": advanced,
    }
    logger.info("reputation.evaluate_warmup_and_shed_4h: %s", summary)
    return summary


@celery.task(
    name="src.app.core.email.reputation.tasks.check_blocked_until_expiry_hourly",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def check_blocked_until_expiry_hourly(self) -> int:
    """Hourly recovery sweep. Returns count of rows flipped back to
    ``ok``."""
    return asyncio.run(_run_recovery())


async def _run_recovery() -> int:
    async with async_session() as session:
        recovered = await shed.sweep_blocked_until_expiry(session)
    if recovered:
        logger.info(
            "reputation.check_blocked_until_expiry_hourly: recovered=%d rows",
            recovered,
        )
    return recovered


@celery.task(
    name="src.app.core.email.reputation.tasks.trim_reputation_buckets_hourly",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def trim_reputation_buckets_hourly(self) -> int:
    """Hourly Redis-bucket sweep. Redundant with Redis TTL — kept as
    a defensive catch-net for hypothetical writes-without-TTL."""
    return asyncio.run(counters.trim_older_than_24h_all_orgs())


__all__ = [
    "check_blocked_until_expiry_hourly",
    "evaluate_warmup_and_shed_4h",
    "trim_reputation_buckets_hourly",
]
