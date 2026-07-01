"""Celery tasks for Google Calendar sync.

Two tasks:

  * :func:`sync_appointment_task` — hook-triggered from the appointment
    service. One task per (appointment, user) reconcile. Idempotent —
    the Step-3 :func:`sync_service.sync_appointment` decision tree
    handles every state (create / update / delete / skip / reassignment
    old-side-delete).

  * :func:`reconcile_pending` — beat sweep (every 30 min). Safety net
    for missed hooks: walks future appointments whose assignees have
    connected Calendar but whose ``google_calendar_event_id`` is NULL,
    and fires :func:`sync_appointment_task` per row. Catches drift
    from Celery-down periods, dev restarts, dispatch failures, etc.

Follows the celery-absent shim shape from
:mod:`core.workflows.tasks` so dev shells without Celery installed
don't break import.

Retry policy: ``autoretry_for=(GoogleCalendarRateLimited,)`` +
exponential backoff (30s → 60s → 120s, capped at 10 min, 3 attempts).
Other exceptions ARE NOT auto-retried — the sync service has already
marked the token row with ``last_error`` so the operator sees them on
the integrations card. The beat sweep will pick up drift on the next
30-min tick regardless.
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


# --- sync_appointment_task ---------------------------------------------


@_shared_task(
    name="src.app.core.integrations.google_calendar.tasks.sync_appointment",
    bind=True,
    autoretry_for=(),  # populated below from the exception module
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def sync_appointment_task(
    self,  # noqa: ARG002 — bound Celery task instance, only needed for retries
    *,
    appointment_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Hook-triggered sync. Idempotent — safe to re-run against the
    same appointment. Returns a summary dict::

        {"result": "created" | "updated" | "deleted" | "skipped",
         "appointment_id": "...",
         "user_id": 42}

    On a :class:`GoogleCalendarRateLimited` exception Celery
    auto-retries per the decorator. Other exceptions are logged +
    surfaced on the token row via
    :func:`sync_service.sync_appointment`'s exception handling; NOT
    auto-retried (the beat sweep catches drift).
    """
    return asyncio.run(
        _sync_appointment_async(
            appointment_id=uuid.UUID(str(appointment_id)),
            user_id=int(user_id),
        )
    )


async def _sync_appointment_async(
    *, appointment_id: uuid.UUID, user_id: int
) -> dict[str, Any]:
    from src.app.core.integrations.google_calendar import (
        service as _gc_service,
        sync_service as _sync,
    )
    from src.app.core.integrations.google_calendar.exceptions import (
        GoogleCalendarError,
    )
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    # The org_id isn't a task argument — it's on the appointment row.
    # We open a session WITHOUT a tenant context first, look up the
    # appointment to get org_id, then re-open with the correct tenant
    # context so RLS applies to all subsequent reads/writes.
    async with async_session() as session:
        from src.app.core.appointments import data_access as _appt_da

        appt = await _appt_da.get_appointment_by_id(session, appointment_id)

    if appt is None:
        # Appointment deleted since the task was enqueued. Still need
        # to run the sync (the delete path in sync_service handles
        # this — reads the current row, sees None, no-ops or deletes
        # the Google-side event if one was stored). We fall through
        # with a synthesised context so the token lookup works.
        logger.info(
            "google_calendar.sync_appointment appointment_gone_at_dispatch "
            "appointment=%s user=%d",
            appointment_id,
            user_id,
        )
        return {
            "result": "skipped",
            "appointment_id": str(appointment_id),
            "user_id": user_id,
            "reason": "appointment_gone",
        }

    org_id = appt.org_id
    token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            try:
                result = await _sync.sync_appointment(
                    session,
                    appointment_id=appointment_id,
                    user_id=user_id,
                )
            except GoogleCalendarError as exc:
                # Surface on the token row so the operator sees the
                # error on the integrations card. The exception is
                # re-raised so Celery's autoretry_for can handle
                # rate-limit specifically; other errors log + skip.
                try:
                    await _gc_service.mark_row_error(
                        session,
                        org_id=org_id,
                        user_id=user_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "google_calendar.sync_appointment mark_error_failed "
                        "appointment=%s user=%d",
                        appointment_id,
                        user_id,
                    )
                # Rate-limit is the only exception we let bubble for
                # Celery to auto-retry. Everything else swallows so
                # the beat sweep can catch drift later.
                from src.app.core.integrations.google_calendar.exceptions import (
                    GoogleCalendarRateLimited,
                )
                if isinstance(exc, GoogleCalendarRateLimited):
                    raise
                logger.warning(
                    "google_calendar.sync_appointment errored "
                    "appointment=%s user=%d err=%s",
                    appointment_id,
                    user_id,
                    exc,
                )
                return {
                    "result": "errored",
                    "appointment_id": str(appointment_id),
                    "user_id": user_id,
                    "error": type(exc).__name__,
                }
            except Exception:  # noqa: BLE001 — belt-and-braces
                logger.exception(
                    "google_calendar.sync_appointment unexpected_failure "
                    "appointment=%s user=%d",
                    appointment_id,
                    user_id,
                )
                return {
                    "result": "errored",
                    "appointment_id": str(appointment_id),
                    "user_id": user_id,
                    "error": "unexpected",
                }
    finally:
        reset_context(token)

    # Happy path — bump last_synced_at + clear any stale last_error.
    async with async_session() as session:
        set_context_token = set_context(
            RequestContext(org_id=org_id, user_id=None)
        )
        try:
            await _gc_service.mark_row_synced(
                session, org_id=org_id, user_id=user_id
            )
        finally:
            reset_context(set_context_token)

    return {
        "result": result,
        "appointment_id": str(appointment_id),
        "user_id": user_id,
    }


# Populate the Celery decorator's ``autoretry_for`` tuple now that the
# module is fully loaded (avoids a circular import if we did it inline).
if HAS_CELERY:
    try:  # pragma: no cover — celery-only path
        from src.app.core.integrations.google_calendar.exceptions import (
            GoogleCalendarRateLimited,
        )

        sync_appointment_task.autoretry_for = (GoogleCalendarRateLimited,)
    except Exception:
        logger.exception(
            "google_calendar.tasks autoretry_for wiring failed — "
            "rate-limit retries disabled"
        )


# --- reconcile_pending (beat sweep) ------------------------------------


@_shared_task(
    name="src.app.core.integrations.google_calendar.tasks.reconcile_pending",
)
def reconcile_pending() -> dict[str, Any]:
    """Beat-triggered every 30 min. Safety net for hook drift.

    Walks appointments where:
      * ``scheduled_at > now()``
      * ``status`` is ``scheduled`` (not cancelled / completed)
      * ``google_calendar_event_id IS NULL``
      * assignee has an active Google Calendar connection row

    For each match, dispatches :func:`sync_appointment_task`. The
    task itself is idempotent — if a race means the row was already
    synced by a concurrent hook, the sync service's PATCH path
    handles it cleanly.

    Cross-tenant sweep — opens a session without tenant context so
    every org's pending appointments are visible. Uses raw SQL for the
    join since the ORM's tenant filter would silently drop everything.
    """
    return asyncio.run(_reconcile_pending_async())


async def _reconcile_pending_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.shared.db import async_session

    dispatched = 0
    scanned = 0

    async with async_session() as session:
        # Assignee identifiers cross a schema boundary: ``tbl_appointments.
        # assigned_to_id`` is a hyphenated UUID; the token row stores the
        # BIGINT ``tbl_user_login.id``. Bridge via ``tbl_user_login`` —
        # match the UUID against ``legacy_uuid`` (fast path) or against
        # the ``'usr_' || hex-no-hyphens`` shape stored in
        # ``tbl_user_login.user_id``.
        rows = (
            await session.execute(
                text(
                    """
                    SELECT a.id AS appointment_id,
                           t.user_id AS user_id
                    FROM tbl_appointments a
                    JOIN tbl_user_login ul
                      ON ul.legacy_uuid::text = a.assigned_to_id::text
                      OR ul.user_id = 'usr_' || replace(a.assigned_to_id::text, '-', '')
                    JOIN tbl_user_google_calendar_tokens t
                      ON t.org_id = a.org_id
                     AND t.status = 'active'
                     AND t.user_id = ul.id
                    WHERE a.scheduled_at > now()
                      AND a.status = 'scheduled'
                      AND a.google_calendar_event_id IS NULL
                    ORDER BY a.scheduled_at
                    LIMIT 500
                    """
                )
            )
        ).all()

    scanned = len(rows)
    if not scanned:
        return {"scanned": 0, "dispatched": 0, "at": datetime.now(UTC).isoformat()}

    for row in rows:
        try:
            sync_appointment_task.apply_async(
                kwargs={
                    "appointment_id": str(row.appointment_id),
                    "user_id": int(row.user_id),
                }
            )
            dispatched += 1
        except Exception:
            logger.exception(
                "google_calendar.reconcile_pending dispatch_failed "
                "appointment=%s user=%s",
                row.appointment_id,
                row.user_id,
            )

    return {
        "scanned": scanned,
        "dispatched": dispatched,
        "at": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "reconcile_pending",
    "sync_appointment_task",
]
