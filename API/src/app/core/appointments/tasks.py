"""Celery tasks for the appointments module.

One beat-scheduled task today — :func:`scan_for_reminders` — sweeps
``tbl_appointments`` every 15 minutes and publishes reminder events
for rows that fall inside the matching ``[now+offset-30m,
now+offset+30m)`` half-hour bracket around each configured offset.

Reminder offsets are per-org — see
``tbl_org_settings.appointment_reminder_offsets_minutes``. The default
list ``[1440, 60]`` keeps every existing org firing at 24h + 1h before
scheduled_at, matching the pre-configurable behaviour.

Every fire publishes a generic ``appointment.reminder_due`` event
carrying ``minutes_before`` in the payload — new automation triggers
and the in-app notification handler subscribe to this. For backward
compatibility, offsets 1440 / 60 ALSO publish the legacy
``appointment.reminder_24h`` / ``appointment.reminder_1h`` events so
the two seed-time automation triggers that listen on those exact
names keep firing untouched.

The ``(trigger_id, event_id)`` uniqueness index on
``tbl_automation_runs`` absorbs the overlap between sweep ticks —
event IDs are ``appointment_reminder_due:{appt.id}:{minutes_before}``.

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
from datetime import UTC, datetime, timedelta
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


# Half-window each side of every configured offset. The beat scheduler
# ticks every 15 minutes, so a 30-minute half-window covers every
# appointment exactly once across two ticks even when the scheduler
# skews; the dispatcher's ``(trigger_id, event_id)`` uniqueness
# absorbs the double-publish in the overlap.
_HALF_WINDOW = timedelta(minutes=30)
# Fallback if the settings row cannot be loaded (e.g. brand-new org
# that has never touched Settings and the get_or_create hasn't run
# yet). Matches the JSONB column's server default.
_DEFAULT_OFFSETS_MINUTES = (1440, 60)


@_shared_task(
    name="src.app.core.appointments.tasks.scan_for_reminders",
)
def scan_for_reminders() -> dict[str, Any]:
    """Beat-scheduled sweep — fires configured reminder events for any
    appointment whose ``scheduled_at`` falls inside any of the per-org
    offset brackets. Returns a small summary dict for the worker logs.
    """
    return asyncio.run(_scan_for_reminders_async())


async def _scan_for_reminders_async() -> dict[str, Any]:
    from src.app.core.appointments import data_access as _da
    from src.app.core.settings import data_access as _settings_da
    from src.app.shared.db import async_session

    now = datetime.now(UTC)

    # Load every org's reminder-offset list in one query; small table
    # (one row per org). Orgs without a row fall back to the default
    # 24h + 1h so behaviour matches the JSONB server default before
    # ``get_or_create`` ever runs.
    async with async_session() as session:
        org_offsets = await _load_org_offsets(session, _settings_da)

    # Compute the union of every configured offset across all orgs.
    # For each unique offset we run ONE cross-tenant windowed query,
    # then filter per-appointment by "is this offset actually enabled
    # for THIS org". Two unique offsets is the steady-state (most orgs
    # keep the [1440, 60] default) so this stays at ~2 SELECTs.
    all_offsets: set[int] = set()
    for offsets in org_offsets.values():
        all_offsets.update(offsets)
    if not all_offsets:
        all_offsets.update(_DEFAULT_OFFSETS_MINUTES)

    total_found = 0
    total_published = 0

    async with async_session() as session:
        for minutes_before in sorted(all_offsets, reverse=True):
            window_start = now + timedelta(minutes=minutes_before) - _HALF_WINDOW
            window_end = now + timedelta(minutes=minutes_before) + _HALF_WINDOW
            due = await _da.find_due_for_reminder(
                session, window_start=window_start, window_end=window_end
            )
            total_found += len(due)
            for appt in due:
                org_offset_list = org_offsets.get(appt.org_id, _DEFAULT_OFFSETS_MINUTES)
                if minutes_before not in org_offset_list:
                    continue
                ok = await _publish_reminder(
                    session,
                    appt=appt,
                    minutes_before=minutes_before,
                )
                if ok:
                    total_published += 1

    logger.info(
        "appointments.scan_for_reminders tick done found=%d published=%d offsets=%s",
        total_found,
        total_published,
        sorted(all_offsets, reverse=True),
    )
    return {
        "found": total_found,
        "published": total_published,
        "offsets": sorted(all_offsets, reverse=True),
    }


async def _load_org_offsets(session, settings_da) -> dict[uuid.UUID, tuple[int, ...]]:
    """Return ``{org_id: (offsets...)}`` for every org with a settings
    row. Orgs missing a row (never touched Settings) fall through to
    the module default at call sites.
    """
    try:
        rows = await settings_da.list_all_org_settings(session)
    except AttributeError:
        # Older DAL revisions without the bulk helper — fall back to
        # a direct SELECT to avoid failing the whole sweep.
        from sqlalchemy import select as _select

        from src.app.core.settings.models import OrgSettings

        rows = list(
            (
                await session.execute(
                    _select(
                        OrgSettings.org_id,
                        OrgSettings.appointment_reminder_offsets_minutes,
                    )
                )
            ).all()
        )
        return {
            org_id: tuple(int(x) for x in (offsets or _DEFAULT_OFFSETS_MINUTES))
            for org_id, offsets in rows
        }
    return {
        row.org_id: tuple(int(x) for x in (row.appointment_reminder_offsets_minutes or ()))
        for row in rows
    }


async def _publish_reminder(
    session,
    *,
    appt,
    minutes_before: int,
) -> bool:
    """Build the reminder envelope + publish via the bus, then create
    the in-app notification for the assignee.

    Hydrates contact + organisation for the renderer; sets a request
    context for the dispatcher subscriber so its session opens with
    ``org_id`` scoped correctly. Returns True when the publish call
    completed.

    Publishes ``appointment.reminder_due`` for all offsets. For the
    two legacy offsets (1440, 60) also publishes the historical
    ``appointment.reminder_24h`` / ``appointment.reminder_1h`` events
    so the seeded automation triggers wired to those exact names keep
    firing without a data migration.
    """
    try:
        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.notifications import service as notifications_service
        from src.app.core.tenants.models import Organization
        from src.app.shared.context import (
            RequestContext,
            reset_context,
            set_context,
        )

        contact = (
            await session.execute(_select(Contact).where(Contact.id == appt.contact_id))
        ).scalar_one_or_none()
        org = (
            await session.execute(_select(Organization).where(Organization.id == appt.org_id))
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "appointment_id": str(appt.id),
            "contact_id": str(appt.contact_id),
            "scheduled_at": appt.scheduled_at.isoformat(),
            "location": appt.location,
            "minutes_before": minutes_before,
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
        # dispatcher — open their own sessions but read
        # ``get_context().org_id`` to scope their writes. Set the
        # context for the publish duration so the dispatcher's
        # trigger lookup + run insert lands in the right tenant.
        token = set_context(RequestContext(org_id=appt.org_id, user_id=None))
        try:
            await events_publish(
                "appointment.reminder_due",
                payload,
                org_id=appt.org_id,
                event_id=f"appointment_reminder_due:{appt.id}:{minutes_before}",
            )
            # Back-compat named events for the seeded automation
            # triggers that were wired to the old event names.
            if minutes_before == 1440:
                await events_publish(
                    "appointment.reminder_24h",
                    payload,
                    org_id=appt.org_id,
                    event_id=f"appointment_reminder_24h:{appt.id}",
                )
            elif minutes_before == 60:
                await events_publish(
                    "appointment.reminder_1h",
                    payload,
                    org_id=appt.org_id,
                    event_id=f"appointment_reminder_1h:{appt.id}",
                )
        finally:
            reset_context(token)

        # In-app notification for the assignee. `notify()` is
        # non-raising and opens its own session, so a socket / DB
        # hiccup here never breaks the publish loop above.
        if appt.assigned_to_id is not None:
            await notifications_service.notify(
                org_id=appt.org_id,
                user_id=appt.assigned_to_id,
                type="appointment.reminder_due",
                title=_reminder_title(appt, minutes_before),
                body=_reminder_body(appt, contact),
                payload={
                    "appointment_id": str(appt.id),
                    "contact_id": str(appt.contact_id) if appt.contact_id else None,
                    "contact_name": (contact.full_name if contact is not None else None),
                    "scheduled_at": appt.scheduled_at.isoformat(),
                    "minutes_before": minutes_before,
                    "location": appt.location,
                },
            )
        return True
    except Exception:
        logger.exception(
            "appointments.scan_for_reminders publish_failed appt=%s offset=%s",
            getattr(appt, "id", None),
            minutes_before,
        )
        return False


def _reminder_title(appt, minutes_before: int) -> str:
    lead = _humanize_lead(minutes_before)
    return f"Reminder: {appt.title} in {lead}"


def _reminder_body(appt, contact) -> str:
    parts: list[str] = []
    when_human = appt.scheduled_at.strftime("%a %b %d, %I:%M %p")
    parts.append(when_human)
    if contact is not None and contact.full_name:
        parts.append(f"with {contact.full_name}")
    if appt.location:
        parts.append(f"at {appt.location}")
    return " ".join(parts)


def _humanize_lead(minutes_before: int) -> str:
    if minutes_before % 1440 == 0:
        days = minutes_before // 1440
        return f"{days} day" if days == 1 else f"{days} days"
    if minutes_before % 60 == 0:
        hours = minutes_before // 60
        return f"{hours}h"
    return f"{minutes_before}m"


__all__ = ["scan_for_reminders"]
