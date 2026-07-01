"""Celery tasks for the follow-ups module.

Currently one task:

  * :func:`groom_stale_open_tasks` — nightly cross-tenant sweep that
    flips ``open`` tasks whose ``due_at`` is more than 7 days in the
    past to the terminal ``missed`` status. Bounds the size of the
    dashboard's Overdue bucket so it doesn't grow unbounded, and
    preserves history under the Missed filter for audit.

Beat schedule: ``crontab(hour=2, minute=0)`` — 02:00 UTC. A 7-day
threshold means the ±14-hour timezone slack (org UTC vs local) doesn't
matter — no row is auto-closed while it's still "recent" in any
timezone we serve.

Follows the celery-absent shim shape from
:mod:`core.workflows.tasks` so dev shells without Celery installed
don't break import.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
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


@_shared_task(
    name="src.app.core.tasks.tasks.groom_stale_open_tasks",
)
def groom_stale_open_tasks() -> dict[str, Any]:
    """Beat-triggered daily. Cross-tenant sweep.

    Raw SQL because we deliberately want to bypass the tenant filter
    (same pattern as :func:`core.integrations.google_calendar.tasks.
    reconcile_pending`). Every affected row gets an audit entry
    (``tasks.auto_missed``) so the change is traceable.
    """
    return asyncio.run(_groom_stale_open_tasks_async())


async def _groom_stale_open_tasks_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.core.audit import service as audit_service
    from src.app.shared.db import async_session

    swept = 0

    async with async_session() as session:
        # Flip stale-open rows in one shot, returning the ids +
        # org_ids so we can emit per-row audit entries under the
        # correct tenant context.
        rows = (
            await session.execute(
                text(
                    """
                    UPDATE tbl_tasks
                       SET status = 'missed',
                           updated_at = now()
                     WHERE status = 'open'
                       AND due_at < (now() - INTERVAL '7 days')
                    RETURNING id, org_id
                    """
                )
            )
        ).all()
        await session.commit()

    for row in rows:
        try:
            await _write_audit(
                org_id=row.org_id,
                task_id=row.id,
            )
            swept += 1
        except Exception:  # noqa: BLE001 — audit best-effort
            logger.exception(
                "groom_stale_open_tasks audit_write_failed task=%s",
                row.id,
            )

    return {
        "swept": swept,
        "at": datetime.now(UTC).isoformat(),
    }


async def _write_audit(*, org_id: uuid.UUID, task_id: uuid.UUID) -> None:
    """Emit ``tasks.auto_missed`` under the affected row's tenant
    context so the linked contact's timeline reflects the change."""
    from src.app.shared.audit import log_entity_change
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )

    token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        await log_entity_change(
            action="tasks.auto_missed",
            entity_type="task",
            entity_id=task_id,
            after={"status": "missed"},
        )
    finally:
        reset_context(token)


__all__ = ["groom_stale_open_tasks"]
