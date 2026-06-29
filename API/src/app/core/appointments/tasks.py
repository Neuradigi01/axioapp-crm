"""Celery tasks for the appointments module.

One beat-scheduled task today — :func:`scan_for_reminders` — sweeps
``tbl_appointments`` every 15 minutes and publishes
``appointment.reminder_24h`` / ``appointment.reminder_1h`` domain
events for rows that fall inside the matching ``[now+window-30m,
now+window+30m)`` half-hour bracket. The
``(trigger_id, event_id)`` uniqueness index on
``tbl_automation_runs`` absorbs the overlap between sweep ticks —
even if the beat fires the scan twice during the 24h window, the
second publish lands on the same deterministic ``event_id`` and the
dispatcher's idempotency check drops it.

Convention: ``@shared_task`` wrappers call
``asyncio.run(_async_helper(...))`` per ``src/celery/worker.py``'s
engine-reset hooks. Don't write ``async def`` tasks — they cannot be
called as ``.delay()`` and the prefork worker can't drive them.

The task runs with NO tenant context — :func:`data_access.find_due_for_reminder`
intentionally skips the ``do_orm_execute`` filter so the sweep
returns rows for every org in one pass; ``set_context(...)`` is
opened per-publish so any downstream subscriber that calls
:func:`get_context` sees the right ``org_id``.

Mirrors the celery-absent shim shape of
:mod:`core.automation.tasks` so dev shells without Celery installed
don't break import; ``apply_async`` becomes a no-op so the beat
schedule entry still resolves under ``CELERY_ENABLED=False``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
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


# Half-window each side of the canonical 24h / 1h offset. The beat
# scheduler ticks every 15 minutes, so a 30-minute half-window covers
# every appointment exactly once across two ticks even when the
# scheduler skews; the dispatcher's ``(trigger_id, event_id)``
# uniqueness absorbs the double-publish in the overlap.
_HALF_WINDOW = timedelta(minutes=30)
# Reminder offsets — kept as module-level constants so tests can
# poke them without monkey-patching the body.
_REMINDER_24H_OFFSET = timedelta(hours=24)
_REMINDER_1H_OFFSET = timedelta(hours=1)


@_shared_task(
    name="src.app.core.appointments.tasks.scan_for_reminders",
)
def scan_for_reminders() -> dict[str, Any]:
    """Beat-scheduled sweep — fires the two reminder events for any
    appointment whose ``scheduled_at`` falls inside the 24h or 1h
    bracket. Returns a small summary dict ``{found_24h, found_1h,
    published}`` for the worker logs."""
    return asyncio.run(_scan_for_reminders_async())


async def _scan_for_reminders_async() -> dict[str, Any]:
    from src.app.core.appointments import data_access as _da
    from src.app.shared.db import async_session

    now = datetime.now(timezone.utc)

    # 24h bracket centred on ``now + 24h``.
    win24_start = now + _REMINDER_24H_OFFSET - _HALF_WINDOW
    win24_end = now + _REMINDER_24H_OFFSET + _HALF_WINDOW
    # 1h bracket centred on ``now + 1h``.
    win1_start = now + _REMINDER_1H_OFFSET - _HALF_WINDOW
    win1_end = now + _REMINDER_1H_OFFSET + _HALF_WINDOW

    published_24h = 0
    published_1h = 0

    async with async_session() as session:
        due_24h = await _da.find_due_for_reminder(
            session, window_start=win24_start, window_end=win24_end
        )
        due_1h = await _da.find_due_for_reminder(
            session, window_start=win1_start, window_end=win1_end
        )

        for appt in due_24h:
            ok = await _publish_reminder(
                session,
                appt=appt,
                event_type="appointment.reminder_24h",
                event_id_prefix="appointment_reminder_24h",
            )
            if ok:
                published_24h += 1

        for appt in due_1h:
            ok = await _publish_reminder(
                session,
                appt=appt,
                event_type="appointment.reminder_1h",
                event_id_prefix="appointment_reminder_1h",
            )
            if ok:
                published_1h += 1

    logger.info(
        "appointments.scan_for_reminders ticks done found_24h=%d "
        "found_1h=%d published_24h=%d published_1h=%d",
        len(due_24h),
        len(due_1h),
        published_24h,
        published_1h,
    )
    return {
        "found_24h": len(due_24h),
        "found_1h": len(due_1h),
        "published_24h": published_24h,
        "published_1h": published_1h,
    }


async def _publish_reminder(
    session,
    *,
    appt,
    event_type: str,
    event_id_prefix: str,
) -> bool:
    """Build the reminder envelope + publish via the bus.

    Hydrates contact + organisation for the renderer; sets a request
    context for the dispatcher subscriber so its session opens with
    ``org_id`` scoped correctly. Returns True when the publish call
    completed (regardless of subscriber outcome — those are absorbed
    by the bus + logged)."""
    try:
        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization
        from src.app.shared.context import (
            RequestContext,
            reset_context,
            set_context,
        )

        contact = (
            await session.execute(
                _select(Contact).where(Contact.id == appt.contact_id)
            )
        ).scalar_one_or_none()
        org = (
            await session.execute(
                _select(Organization).where(Organization.id == appt.org_id)
            )
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "appointment_id": str(appt.id),
            "contact_id": str(appt.contact_id),
            "scheduled_at": appt.scheduled_at.isoformat(),
            "location": appt.location,
            "appointment": {
                "id": str(appt.id),
                "title": appt.title,
                "purpose": appt.purpose,
                "scheduled_at": appt.scheduled_at.isoformat(),
                "duration_min": appt.duration_min,
                "location": appt.location,
            },
        }
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        # The bus's subscribers — primarily the automation
        # dispatcher — open their own sessions; but they read
        # ``get_context().org_id`` to scope their writes. Set the
        # context for the publish duration so the dispatcher's
        # trigger lookup + run insert lands in the right tenant.
        token = set_context(RequestContext(org_id=appt.org_id, user_id=None))
        try:
            await events_publish(
                event_type,
                payload,
                org_id=appt.org_id,
                event_id=f"{event_id_prefix}:{appt.id}",
            )
        finally:
            reset_context(token)
        return True
    except Exception:
        logger.exception(
            "appointments.scan_for_reminders publish_failed "
            "appt=%s event=%s",
            getattr(appt, "id", None),
            event_type,
        )
        return False


__all__ = ["scan_for_reminders"]
