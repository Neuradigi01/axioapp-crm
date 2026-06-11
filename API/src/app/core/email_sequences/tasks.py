"""Celery task wrapper for the email-sequences scheduler.

The actual business logic lives in `scheduler.tick()`. This module
exists only so Celery beat can register `tick_email_sequences` as a
periodic task (beat needs a `@shared_task` to drive; pure `async def`
coroutines aren't callable as `.delay()`).

Convention: `@shared_task` wrapper synchronously calls
`asyncio.run(...)` per the project's `src/celery/worker.py` engine-
reset hooks (matches `core/subscriptions/tasks.py`, `core/email/
tasks.py`, `core/campaigns/tasks.py`).
"""
from __future__ import annotations

import asyncio
from typing import Any

from celery import shared_task

from src.app.core.email_sequences.scheduler import tick


@shared_task(name="src.app.core.email_sequences.tasks.tick_email_sequences")
def tick_email_sequences() -> dict[str, Any]:
    """Beat-driven sweep — every 60s. Returns the count of
    enrollment-step rows the tick processed; mostly for log /
    observability."""
    processed = asyncio.run(tick())
    return {"processed": processed}


__all__ = ["tick_email_sequences"]
