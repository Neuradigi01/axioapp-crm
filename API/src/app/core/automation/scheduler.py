"""Daily time-anchored scan logic for the automation engine.

Two pure-async scan functions powering the Step-12 time-based
triggers:

  * :func:`scan_birthdays` — finds every contact whose
    ``date_of_birth`` matches today (month + day) in the org's
    timezone + publishes ``contact.birthday`` for each.
  * :func:`scan_stale_leads` — finds every ``active`` lead with no
    activity in the last 30 days + publishes ``lead.stale_30d``
    for each.

The Celery beat layer in :mod:`core.automation.tasks` calls
:func:`run_daily_time_based_scan`, which sequences the two scans
and reports counts back. Keeping the scan logic out of the Celery
task lets tests exercise it via plain ``asyncio.run`` without
mocking the prefork worker.

Idempotency strategy:

  * Birthday events use ``event_id=f"contact_birthday:{contact_id}:{year}"``
    so multiple beat ticks within a single day collapse into one
    ``tbl_automation_runs`` row per contact per year.
  * Stale-lead events use
    ``event_id=f"lead_stale_30d:{lead_id}:{first_stale_date}"`` where
    ``first_stale_date`` is the ISO date of the lead's
    ``last_activity_at + 30 days`` boundary. Daily re-scans of the
    same lead produce the same event_id → the dispatcher's
    ``(trigger_id, event_id)`` uniqueness drops the duplicate so the
    operator sees a single "lead went stale on YYYY-MM-DD" fire
    rather than 60 daily nags.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Number of days of inactivity before a lead is considered stale.
# The seeded "Lead Stale 30d" trigger binds to the ``lead.stale_30d``
# event type — if you change this constant you must move the event
# type + the seeded trigger together (a future 7d / 90d variant
# would land as additional events).
_STALE_DAYS = 30


async def scan_birthdays(session, *, today: date) -> list[dict[str, Any]]:
    """Return per-contact ``contact.birthday`` event envelopes for
    every Contact whose ``(month, day)`` matches ``today``.

    Cross-tenant — relies on ``contacts.data_access.find_birthdays_on``
    opening with no tenant context so every org's matching contacts
    land in one pass. The caller (typically the Celery beat task)
    iterates the returned list + publishes each via the bus.
    """
    from src.app.core.contacts import data_access as contacts_da
    from src.app.core.contacts.models import Contact  # noqa: F401

    rows = await contacts_da.find_birthdays_on(session, month=today.month, day=today.day)
    envelopes: list[dict[str, Any]] = []
    for contact in rows:
        age_turning = None
        if contact.date_of_birth is not None:
            age_turning = today.year - contact.date_of_birth.year
        envelopes.append(
            {
                "event_type": "contact.birthday",
                "event_id": (f"contact_birthday:{contact.id}:{today.year}"),
                "org_id": contact.org_id,
                "payload": {
                    "contact_id": str(contact.id),
                    "age_turning": age_turning,
                    "date_of_birth": (
                        contact.date_of_birth.isoformat() if contact.date_of_birth else None
                    ),
                    "contact": {
                        "id": str(contact.id),
                        "full_name": contact.full_name,
                        "email": contact.email,
                        "phone": contact.phone,
                        "date_of_birth": (
                            contact.date_of_birth.isoformat() if contact.date_of_birth else None
                        ),
                    },
                },
            }
        )
    return envelopes


async def scan_stale_leads(
    session, *, now: datetime, stale_days: int = _STALE_DAYS
) -> list[dict[str, Any]]:
    """Return per-lead ``lead.stale_30d`` event envelopes for every
    active Lead with no activity in the last ``stale_days`` days.

    The ``event_id`` embeds the first-stale date so multiple daily
    re-scans for the same lead collapse — the operator gets one
    "lead went stale on YYYY-MM-DD" fire, not a daily nag stream.
    The first-stale date is computed as
    ``last_activity_at + stale_days`` (truncated to date); for
    never-touched leads we use ``created_at + stale_days``.
    """
    from sqlalchemy import select as _select

    from src.app.core.contacts.models import Contact
    from src.app.core.leads import data_access as leads_da

    inactive_since = now - timedelta(days=stale_days)
    rows = await leads_da.find_stale_leads(session, inactive_since=inactive_since)

    # Per-lead hydrate the contact for the renderer.
    envelopes: list[dict[str, Any]] = []
    for lead in rows:
        contact = (
            await session.execute(_select(Contact).where(Contact.id == lead.contact_id))
        ).scalar_one_or_none()
        anchor = lead.last_activity_at or lead.created_at
        if anchor is None:
            # A row with neither last_activity_at nor created_at
            # is malformed; skip it rather than crash the sweep.
            continue
        first_stale_date = (anchor + timedelta(days=stale_days)).date()
        days_since = (now - anchor).days
        payload: dict[str, Any] = {
            "lead_id": str(lead.id),
            "contact_id": (str(lead.contact_id) if lead.contact_id else None),
            "days_since_last_activity": days_since,
            "last_activity_at": (
                lead.last_activity_at.isoformat() if lead.last_activity_at else None
            ),
            "lead": {
                "id": str(lead.id),
                "status": (
                    lead.status.value if hasattr(lead.status, "value") else str(lead.status)
                ),
                "pipeline_stage": lead.pipeline_stage,
                "assigned_to_id": (str(lead.assigned_to_id) if lead.assigned_to_id else None),
                "last_activity_at": (
                    lead.last_activity_at.isoformat() if lead.last_activity_at else None
                ),
            },
        }
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        envelopes.append(
            {
                "event_type": "lead.stale_30d",
                "event_id": (f"lead_stale_30d:{lead.id}:{first_stale_date.isoformat()}"),
                "org_id": lead.org_id,
                "payload": payload,
            }
        )
    return envelopes


async def run_daily_time_based_scan(*, now: datetime | None = None) -> dict[str, int]:
    """End-to-end driver — opens its own session, runs both scans,
    publishes every envelope via the bus, and returns counts for the
    worker logs.

    Per-publish a ``RequestContext(org_id=...)`` is set so the
    automation dispatcher's subscriber writes its run row in the
    right tenant scope.
    """
    from sqlalchemy import select as _select

    from src.app.core.events.bus import publish as events_publish
    from src.app.core.tenants.models import Organization
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    if now is None:
        now = datetime.now(UTC)
    today = now.date()

    birthday_published = 0
    stale_published = 0

    async with async_session() as session:
        # Pre-fetch org snapshots for the per-org enrichment of each
        # envelope. Cross-tenant cache keyed by org_id keeps the
        # publish loop from re-querying.
        org_rows = (await session.execute(_select(Organization))).scalars().all()
        org_by_id = {o.id: o for o in org_rows}

        birthday_envelopes = await scan_birthdays(session, today=today)
        stale_envelopes = await scan_stale_leads(session, now=now)

    # Publish outside the read transaction so a slow subscriber can't
    # hold open the read connection.
    for env in birthday_envelopes:
        org = org_by_id.get(env["org_id"])
        if org is not None:
            env["payload"]["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }
        token = set_context(RequestContext(org_id=env["org_id"], user_id=None))
        try:
            try:
                await events_publish(
                    env["event_type"],
                    env["payload"],
                    org_id=env["org_id"],
                    event_id=env["event_id"],
                )
                birthday_published += 1
            except Exception:
                logger.exception(
                    "automation.daily_time_based_scan birthday_publish_failed contact=%s",
                    env["payload"].get("contact_id"),
                )
        finally:
            reset_context(token)

    for env in stale_envelopes:
        org = org_by_id.get(env["org_id"])
        if org is not None:
            env["payload"]["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }
        token = set_context(RequestContext(org_id=env["org_id"], user_id=None))
        try:
            try:
                await events_publish(
                    env["event_type"],
                    env["payload"],
                    org_id=env["org_id"],
                    event_id=env["event_id"],
                )
                stale_published += 1
            except Exception:
                logger.exception(
                    "automation.daily_time_based_scan stale_publish_failed lead=%s",
                    env["payload"].get("lead_id"),
                )
        finally:
            reset_context(token)

    logger.info(
        "automation.daily_time_based_scan done birthdays_found=%d "
        "birthdays_published=%d stale_found=%d stale_published=%d",
        len(birthday_envelopes),
        birthday_published,
        len(stale_envelopes),
        stale_published,
    )
    return {
        "birthdays_found": len(birthday_envelopes),
        "birthdays_published": birthday_published,
        "stale_found": len(stale_envelopes),
        "stale_published": stale_published,
    }


__all__ = [
    "run_daily_time_based_scan",
    "scan_birthdays",
    "scan_stale_leads",
]
