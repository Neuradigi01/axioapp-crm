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

from sqlalchemy import and_, select
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
    "get_walk_in_by_id",
    "insert_walk_in",
    "list_walk_ins_paginated",
    "user_has_active_membership",
]
