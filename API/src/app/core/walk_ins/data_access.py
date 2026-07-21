"""Data-access layer for the walk_ins module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations grouped by concern:

  * Single-row reads
      get_walk_in_by_id
  * Filtered list (sort whitelist + WHERE composition lives in DAL —
    the params are typed enums / dates so there's no business-layer
    parsing here)
      list_walk_ins_paginated
  * Writes (caller commits)
      insert_walk_in, delete_walk_in_row
  * Cross-module verifiers
      contact_exists_in_org — narrow projection check against
        ``tbl_contacts`` for the walk-in create validator
      user_has_active_membership — User ⋈ OrganizationMember check
        used by the reassign target validator
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.models import Contact
from src.app.core.users.models import OrganizationMember, User
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.shared.db.pagination import paginate

_SORT_COLUMNS = {
    "time_in": WalkIn.time_in,
    "created_at": WalkIn.created_at,
    "last_activity_at": WalkIn.last_activity_at,
}


# --- Single-row reads ---------------------------------------------------


async def get_walk_in_by_id(session: AsyncSession, walk_in_id: uuid.UUID) -> WalkIn | None:
    """Single-row read by PK. ``None`` on miss."""
    result = await session.execute(select(WalkIn).where(WalkIn.id == walk_in_id))
    return result.scalar_one_or_none()


# --- Lists --------------------------------------------------------------


async def list_walk_ins_paginated(
    session: AsyncSession,
    *,
    status_filter: WalkInStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    open_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["time_in", "created_at", "last_activity_at"] = "time_in",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[WalkIn], int]:
    """Filtered paginated list.

    ``open_only=True`` → rows with no ``time_out`` (currently
    in-store); ``date_from`` / ``date_to`` window the ``time_in``
    column; ``last_activity_at`` ordering appends ``NULLS LAST`` so
    never-touched walk-ins sink to the bottom of either direction."""
    filters: list[Any] = []
    if status_filter is not None:
        filters.append(WalkIn.status == status_filter)
    if assigned_to is not None:
        filters.append(WalkIn.assigned_to_id == assigned_to)
    if open_only:
        filters.append(WalkIn.time_out.is_(None))
    if date_from is not None:
        filters.append(WalkIn.time_in >= date_from)
    if date_to is not None:
        filters.append(WalkIn.time_in <= date_to)

    where = and_(*filters) if filters else None
    base = select(WalkIn)
    if where is not None:
        base = base.where(where)

    sort_col = _SORT_COLUMNS[sort]
    if sort == "last_activity_at":
        primary = sort_col.asc().nulls_last() if order == "asc" else sort_col.desc().nulls_last()
    else:
        primary = sort_col.asc() if order == "asc" else sort_col.desc()
    base = base.order_by(primary, WalkIn.id.desc())

    return await paginate(session, base, page=page, size=size)


# --- Writes -------------------------------------------------------------


def insert_walk_in(session: AsyncSession, walk_in: WalkIn) -> None:
    """Register an already-constructed WalkIn for INSERT."""
    session.add(walk_in)


async def delete_walk_in_row(session: AsyncSession, walk_in: WalkIn) -> None:
    """Mark a WalkIn row for DELETE. Caller commits."""
    await session.delete(walk_in)


# --- Cross-module verifiers ---------------------------------------------


async def contact_exists_in_org(session: AsyncSession, contact_id: uuid.UUID) -> bool:
    """Narrow-column existence check used by the walk-in create
    validator. The tenant ORM filter ensures only in-org contacts
    are visible; missing → caller raises 422."""
    row = (
        await session.execute(select(Contact.id).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    return row is not None


async def list_walk_ins_by_ids_in_org(
    session: AsyncSession, *, ids: list[uuid.UUID], org_id: uuid.UUID
) -> list[WalkIn]:
    """Batched hydrate for bulk-checkout / bulk-reassign. Empty input
    returns [] without a round-trip. Belt + suspenders on org_id."""
    if not ids:
        return []
    result = await session.execute(
        select(WalkIn).where(WalkIn.id.in_(ids), WalkIn.org_id == org_id)
    )
    return list(result.scalars().all())


async def delete_walk_ins_in_org(
    session: AsyncSession, *, ids: list[uuid.UUID], org_id: uuid.UUID
) -> int:
    """Bulk-delete N walk-ins in one SQL statement. Returns rowcount."""
    if not ids:
        return 0
    stmt = sa_text("DELETE FROM tbl_walk_ins WHERE org_id = :org_id AND id = ANY(:ids)")
    result = await session.execute(stmt, {"org_id": org_id, "ids": list(ids)})
    return int(result.rowcount or 0)


async def rollup_query(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    assigned_to: uuid.UUID | None,
    day_boundary_offset_minutes: int = 0,
) -> Any:
    """One grouped SQL query for the walk-ins KPI card strip.

    `day_boundary_offset_minutes` shifts the "today" cutoff off UTC so
    IST-anchored orgs don't roll over at 5:30 AM local. Service layer
    resolves the org's timezone → offset (defaults to IST 330).
    """
    params: dict[str, Any] = {
        "org_id": org_id,
        "offset_min": day_boundary_offset_minutes,
    }
    scope_clause = ""
    if assigned_to is not None:
        scope_clause = " AND assigned_to_id = :assigned_to"
        params["assigned_to"] = assigned_to

    sql = sa_text(
        f"""
        SELECT
          COUNT(*) FILTER (
            WHERE (time_in + (:offset_min || ' minutes')::interval)::date
                = (NOW() + (:offset_min || ' minutes')::interval)::date
          ) AS today_count,
          COUNT(*) FILTER (
            WHERE (time_in + (:offset_min || ' minutes')::interval)::date
                = (NOW() + (:offset_min || ' minutes')::interval)::date
              AND status = 'converted'
          ) AS today_converted,
          COUNT(*) FILTER (WHERE time_out IS NULL) AS open_now,
          COUNT(*) FILTER (
            WHERE status IN ('interested', 'follow_up')
          ) AS interested_or_follow_up,
          (
            SELECT
              CASE
                WHEN COUNT(*) FILTER (
                  WHERE status IN ('converted', 'left')
                    AND updated_at >= NOW() - INTERVAL '30 days'
                ) = 0 THEN NULL
                ELSE
                  100.0 * COUNT(*) FILTER (
                    WHERE status = 'converted'
                      AND updated_at >= NOW() - INTERVAL '30 days'
                  ) / COUNT(*) FILTER (
                    WHERE status IN ('converted', 'left')
                      AND updated_at >= NOW() - INTERVAL '30 days'
                  )
              END
            FROM tbl_walk_ins
            WHERE org_id = :org_id{scope_clause}
          ) AS conversion_rate_pct,
          (
            SELECT AVG(duration_min)
            FROM tbl_walk_ins
            WHERE org_id = :org_id{scope_clause}
              AND duration_min IS NOT NULL
              AND time_out >= NOW() - INTERVAL '30 days'
          ) AS avg_duration_min,
          -- Only count positive waits (a bad wait_started_at > time_in
          -- would skew the metric silently otherwise).
          (
            SELECT AVG(EXTRACT(EPOCH FROM (time_in - wait_started_at)) / 60)
            FROM tbl_walk_ins
            WHERE org_id = :org_id{scope_clause}
              AND wait_started_at IS NOT NULL
              AND time_in >= wait_started_at
              AND time_in >= NOW() - INTERVAL '30 days'
          ) AS avg_wait_min
        FROM tbl_walk_ins
        WHERE org_id = :org_id{scope_clause}
        """
    )
    return (await session.execute(sql, params)).one()


async def user_has_active_membership(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> bool:
    """True when ``user_uuid`` resolves to a User whose
    ``OrganizationMember`` row is active in ``org_id``. Same join +
    check the contacts / leads / appointments / tasks reassigners use."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


__all__ = [
    "contact_exists_in_org",
    "delete_walk_in_row",
    "delete_walk_ins_in_org",
    "get_walk_in_by_id",
    "insert_walk_in",
    "list_walk_ins_by_ids_in_org",
    "list_walk_ins_paginated",
    "rollup_query",
    "user_has_active_membership",
]
