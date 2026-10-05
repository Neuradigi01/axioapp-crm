"""Data-access layer for the tasks module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations grouped by concern:

  * Single-row reads
      get_task_by_id
  * Lists (service composes WHERE / ORDER; DAL paginates)
      list_tasks_for_entity_query, paginate_tasks_select
  * Writes (caller commits)
      insert_task, delete_task_row, bulk_delete_tasks_by_ids
  * Cross-module verifier
      user_has_active_membership — User ⋈ OrganizationMember check
        used by the reassign target validator
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.users.models import OrganizationMember, User
from src.app.shared.db.pagination import paginate

# --- Single-row reads ---------------------------------------------------


async def get_task_by_id(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


# --- Lists --------------------------------------------------------------


async def list_tasks_for_entity_query(
    session: AsyncSession,
    *,
    related_entity_type: str,
    related_entity_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Tasks attached to one entity, earliest due first (NULLS LAST)
    then newest-created tiebreak. Used by the "Tasks" tab on contact /
    lead detail pages."""
    filters: list[Any] = [
        Task.related_entity_type == related_entity_type,
        Task.related_entity_id == related_entity_id,
    ]
    if status_filter is not None:
        filters.append(Task.status == status_filter)

    base = (
        select(Task).where(*filters).order_by(nulls_last(Task.due_at.asc()), Task.created_at.desc())
    )
    return await paginate(session, base, page=page, size=size)


async def count_tasks_by_bucket(session: AsyncSession, *, scope: list[Any]) -> dict[str, int]:
    """Open / overdue / due-today / done / missed counts in one pass.
    ``scope`` is the WHERE list the service composed (owner or org).
    "Today" uses the database's current date, matching the list's
    ``due_filter=today``."""
    is_open = Task.status == TaskStatus.open
    stmt = select(
        func.count().filter(is_open).label("open"),
        func.count().filter(is_open, Task.due_at < func.now()).label("overdue"),
        func.count()
        .filter(is_open, func.date(Task.due_at) == func.current_date())
        .label("due_today"),
        func.count().filter(Task.status == TaskStatus.done).label("done"),
        func.count().filter(Task.status == TaskStatus.missed).label("missed"),
    ).where(*scope)
    row = (await session.execute(stmt)).one()
    return dict(row._mapping)


async def paginate_tasks_select(
    session: AsyncSession,
    stmt: Select,
    *,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Execute a pre-built ``select(Task)`` statement under shared
    pagination. Service composes WHERE + ORDER via its filter helper
    and hands the assembled statement here."""
    return await paginate(session, stmt, page=page, size=size)


# --- Writes -------------------------------------------------------------


def insert_task(session: AsyncSession, task: Task) -> None:
    """Register an already-constructed Task for INSERT."""
    session.add(task)


async def delete_task_row(session: AsyncSession, task: Task) -> None:
    """Mark a Task row for DELETE. Caller commits."""
    await session.delete(task)


async def bulk_delete_tasks_by_ids(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete N tasks. Belt + suspenders: ``org_id`` in WHERE
    alongside the per-tenant RLS policy. Returns rowcount; caller
    commits."""
    result = await session.execute(delete(Task).where(Task.org_id == org_id, Task.id.in_(ids)))
    return int(result.rowcount or 0)


async def list_tasks_by_ids_in_org(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> list[Task]:
    """Batched hydrate for the bulk-op paths. Empty ``ids`` short-circuits
    without a round-trip. Explicit ``org_id`` predicate belts the RLS
    policy — same shape ``leads.data_access.list_leads_by_ids_in_org``
    uses.

    Prior versions of ``bulk_reassign_tasks`` / ``bulk_mark_done_tasks``
    walked ``ids`` and called ``get_task_by_id`` per iteration, giving
    the router-cap 200 ids ≡ 200 SELECTs. This is the one-shot version
    the service now uses."""
    if not ids:
        return []
    result = await session.execute(select(Task).where(Task.org_id == org_id, Task.id.in_(ids)))
    return list(result.scalars().all())


# --- Cross-module verifier ----------------------------------------------


async def user_has_active_membership(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> bool:
    """True when ``user_uuid`` resolves to a User whose
    ``OrganizationMember`` row is active in ``org_id``. Used by the
    reassign target validator — same join + check the contacts /
    leads / appointments / walk-ins reassigners use."""
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
    "bulk_delete_tasks_by_ids",
    "delete_task_row",
    "get_task_by_id",
    "insert_task",
    "list_tasks_by_ids_in_org",
    "list_tasks_for_entity_query",
    "paginate_tasks_select",
    "user_has_active_membership",
]
