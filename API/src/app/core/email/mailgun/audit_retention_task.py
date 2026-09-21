"""Daily retention sweep for ``tbl_email_inbound_deliveries``.

Kept in its own module (not appended to ``tasks.py``) so the shipped
webhook Celery task and this new retention task don't share a file —
matches the ``orphan_cleanup``/``pending_inbound_sweeper`` pattern
under the same package.

Runs at 05:00 UTC daily (see ``celery_config.py``). Batches deletes
at 10k rows per beat so a large backlog after retention shrink
doesn't stall.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.app.core.email.mailgun.audit_deliveries import sweep_expired
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="src.app.core.email.mailgun.audit_retention_task.sweep_inbound_deliveries_daily",
    bind=True,
)
def sweep_inbound_deliveries_daily(self) -> dict[str, Any]:  # noqa: ARG001
    """Beat-triggered daily. See module docstring."""
    return asyncio.run(_run())


async def _run() -> dict[str, Any]:
    async with async_session() as session:
        return await sweep_expired(session)


__all__ = ["sweep_inbound_deliveries_daily"]
