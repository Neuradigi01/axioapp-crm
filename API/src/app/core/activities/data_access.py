"""Data-access layer for the activities timeline.

Pure query helpers — no transactions, no commits. Leaf module; never
imports a ``service.py``.

Three operations:

  * ``insert_activity`` — INSERT + FLUSH (so ``created_at`` is populated
    for the caller's last-activity bump). No commit; caller owns the
    transaction.
  * ``bump_last_activity`` — UPDATE the parent entity's
    ``last_activity_at`` column, but only when the existing value is
    older than the supplied timestamp. Best-effort by contract — the
    caller wraps it in a try/except.
  * ``list_activities_for_entity`` — paginated read with COUNT, latest
    first. Tenant scoping is automatic via the ORM filter on
    ``TenantScoped``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities.models import Activity, ActivityType


def insert_activity(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    type: ActivityType,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
) -> Activity:
    """Construct an Activity row and register it for INSERT. Caller
    must flush (so ``created_at`` is populated for the last-activity
    bump) and commit."""
    activity = Activity(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        type=type,
        payload=payload or {},
        user_id=user_id,
    )
    session.add(activity)
    return activity


async def bump_last_activity(
    session: AsyncSession,
    *,
    table: type,
    entity_id: uuid.UUID,
    timestamp: datetime,
) -> None:
    """Conditionally UPDATE ``last_activity_at`` on the parent row.

    The WHERE clause only writes when the existing value is older than
    ``timestamp`` (or NULL). No exception handling — the caller traps
    failures so a missing parent row doesn't break the activity insert.
    """
    await session.execute(
        update(table)
        .where(table.id == entity_id)
        .where(
            or_(
                table.last_activity_at.is_(None),
                table.last_activity_at < timestamp,
            )
        )
        .values(last_activity_at=timestamp)
    )


async def list_activities_for_entity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Activity], int]:
    """Return ``(rows, total)`` for one entity's timeline, latest first.

    Tenant scoping is automatic via the ORM filter on ``TenantScoped``.
    """
    base = (
        select(Activity)
        .where(Activity.entity_type == entity_type)
        .where(Activity.entity_id == entity_id)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(Activity)
        .where(Activity.entity_type == entity_type)
        .where(Activity.entity_id == entity_id)
    )
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(base.offset((page - 1) * size).limit(size))).scalars().all()
    return list(rows), int(total)


__all__ = [
    "bump_last_activity",
    "insert_activity",
    "list_activities_for_entity",
]
