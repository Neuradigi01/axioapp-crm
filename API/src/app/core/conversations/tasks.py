"""Celery tasks for the conversations module.

  * :func:`reopen_due_snoozed` — every-minute cross-tenant sweep that
    reopens snoozed conversations whose ``snoozed_until`` has passed
    (the "Snooze until tomorrow 9am" option in the inbox).

Follows the celery-absent shim shape from :mod:`core.tasks.tasks` so
dev shells without Celery installed don't break import.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover — celery absent in dev shells
    HAS_CELERY = False

    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply_async(self, args=None, kwargs=None, **_):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        return _wrap


logger = logging.getLogger(__name__)


@_shared_task(name="src.app.core.conversations.tasks.reopen_due_snoozed")
def reopen_due_snoozed() -> dict[str, Any]:
    """Beat-triggered every minute. Reopens due timed snoozes."""
    return asyncio.run(_reopen_due_snoozed_async())


async def _reopen_due_snoozed_async() -> dict[str, Any]:
    from src.app.core.conversations.service import reopen_due_snoozed_conversations
    from src.app.shared.db import async_session

    async with async_session() as session:
        reopened = await reopen_due_snoozed_conversations(session)
    if reopened:
        logger.info("conversations.reopen_due_snoozed reopened=%d", reopened)
    return {"reopened": reopened, "at": datetime.now(UTC).isoformat()}
