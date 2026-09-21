"""Weekly quarantine auto-purge.

Runs on the Monday 04:00 UTC beat (see ``celery_config.py``). Deletes
held rows older than ``EMAIL_QUARANTINE_AUTO_PURGE_DAYS`` + drops
their on-disk MIME. State flip to ``auto_purged`` preserves the row
for audit; only the payload directory is unlinked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.app.core.email.quarantine import service as quarantine_service
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="src.app.core.email.quarantine.tasks.auto_purge_quarantine",
    bind=True,
)
def auto_purge_quarantine(self) -> dict[str, Any]:  # noqa: ARG001
    """Beat-triggered weekly. See module docstring."""
    return asyncio.run(_run())


async def _run() -> dict[str, Any]:
    async with async_session() as session:
        return await quarantine_service.auto_purge(session)


__all__ = ["auto_purge_quarantine"]
