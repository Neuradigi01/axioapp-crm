"""Pure CRUD for custom events. No transactions, no business logic —
the service layer owns both.

Every SELECT relies on the ``TenantScoped`` loader-criteria event to
inject the tenant filter automatically; explicit ``org_id`` predicates
below are the belt-and-suspenders guard the RLS docs recommend
(direct SQL access from ops, background jobs that flip context, etc.).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_events.models import CustomEvent, CustomEventOccurrence


async def list_events(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    include_deleted: bool = False,
) -> list[CustomEvent]:
    stmt = select(CustomEvent).where(CustomEvent.org_id == org_id)
    if not include_deleted:
        stmt = stmt.where(CustomEvent.deleted_at.is_(None))
    stmt = stmt.order_by(CustomEvent.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    include_deleted: bool = False,
) -> CustomEvent | None:
    stmt = select(CustomEvent).where(
        CustomEvent.org_id == org_id,
        CustomEvent.id == event_id,
    )
    if not include_deleted:
        stmt = stmt.where(CustomEvent.deleted_at.is_(None))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_event_by_key(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_key: str,
) -> CustomEvent | None:
    stmt = select(CustomEvent).where(
        CustomEvent.org_id == org_id,
        CustomEvent.event_key == event_key,
        CustomEvent.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def insert_event(session: AsyncSession, event: CustomEvent) -> None:
    """Stage an INSERT — the service owns commit."""
    session.add(event)


def insert_occurrence(session: AsyncSession, occurrence: CustomEventOccurrence) -> None:
    session.add(occurrence)


async def count_fires_last_30d(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Return ``{event_id: count}`` for the last 30 days.

    Batched (single query IN-list) so the list page renders in one
    round-trip instead of N. Missing event_ids default to 0 in the
    caller.
    """
    if not event_ids:
        return {}
    since = datetime.now(UTC) - timedelta(days=30)
    stmt = (
        select(CustomEventOccurrence.event_id, func.count(CustomEventOccurrence.id))
        .where(
            CustomEventOccurrence.org_id == org_id,
            CustomEventOccurrence.event_id.in_(event_ids),
            CustomEventOccurrence.fired_at >= since,
        )
        .group_by(CustomEventOccurrence.event_id)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


async def list_occurrences(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CustomEventOccurrence], int]:
    total_stmt = select(func.count(CustomEventOccurrence.id)).where(
        CustomEventOccurrence.org_id == org_id,
        CustomEventOccurrence.event_id == event_id,
    )
    total = int((await session.execute(total_stmt)).scalar_one())

    stmt = (
        select(CustomEventOccurrence)
        .where(
            CustomEventOccurrence.org_id == org_id,
            CustomEventOccurrence.event_id == event_id,
        )
        .order_by(CustomEventOccurrence.fired_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def list_occurrences_for_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Contact-timeline read. Joins to the event definition so the
    caller can render ``<event.name> was logged on <fired_at>`` without
    a second round-trip."""
    stmt = (
        select(
            CustomEventOccurrence.id,
            CustomEventOccurrence.event_id,
            CustomEventOccurrence.fired_at,
            CustomEventOccurrence.fired_by_user_id,
            CustomEventOccurrence.payload,
            CustomEvent.event_key,
            CustomEvent.name,
        )
        .join(CustomEvent, CustomEvent.id == CustomEventOccurrence.event_id)
        .where(
            CustomEventOccurrence.org_id == org_id,
            CustomEventOccurrence.contact_id == contact_id,
        )
        .order_by(CustomEventOccurrence.fired_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows: list[dict[str, Any]] = []
    for r in result.all():
        rows.append(
            {
                "id": r[0],
                "event_id": r[1],
                "fired_at": r[2],
                "fired_by_user_id": r[3],
                "payload": r[4],
                "event_key": r[5],
                "event_name": r[6],
            }
        )
    return rows


async def list_scheduled_events_for_hour(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    hour_local: int,
) -> list[CustomEvent]:
    """Return every live ``date_field``-scheduled event on this org
    whose ``schedule_hour_local`` matches ``hour_local``.

    Backs the Celery beat sweeper — called once per (org, hour) tick.
    The sweeper knows the org's timezone + current local hour and
    invokes this for exactly that hour.
    """
    stmt = select(CustomEvent).where(
        CustomEvent.org_id == org_id,
        CustomEvent.schedule_type == "date_field",
        CustomEvent.schedule_hour_local == hour_local,
        CustomEvent.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_all_scheduled_events(session: AsyncSession) -> list[CustomEvent]:
    """Cross-tenant read for the Celery beat sweeper's per-org loop.

    Callers set no tenant context so the ORM-level tenant filter
    doesn't apply — the sweeper needs to iterate every org's
    scheduled events in one pass, then bucket by ``(org_id,
    schedule_hour_local)`` and sweep each bucket at its local hour."""
    stmt = select(CustomEvent).where(
        CustomEvent.schedule_type == "date_field",
        CustomEvent.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "count_fires_last_30d",
    "get_event",
    "get_event_by_key",
    "insert_event",
    "insert_occurrence",
    "list_all_scheduled_events",
    "list_events",
    "list_occurrences",
    "list_occurrences_for_contact",
    "list_scheduled_events_for_hour",
]
