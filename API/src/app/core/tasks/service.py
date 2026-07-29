"""Service layer for tasks.

Three categories of operation:

1. CRUD against the tasks row (`create_task`, `get_task`, `update_task`,
   `delete_task`).
2. The per-entity panel reader (`list_tasks_for_entity`) used by the
   "Tasks" tab on contact/lead detail pages.
3. The "my tasks" reader (`list_my_tasks`) backing the header popover
   — filters by `assigned_to_id == current user` and orders by
   `due_at` (nulls last), which matches what the index supports.

Audit events fire from each write path so the timeline picks up
status changes for free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import case, func, nulls_first, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities
from src.app.core.activities.models import ActivityType
from src.app.core.tasks import data_access as _da
from src.app.core.tasks.models import Task, TaskPriority, TaskStatus
from src.app.core.tasks.schemas import TaskCreate, TaskUpdate
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found

_TASK_ENTITY = "task"

DueFilter = Literal["today", "overdue", "upcoming"]
SortBy = Literal["due_at", "priority", "title", "created_at", "last_activity_at"]
SortDir = Literal["asc", "desc"]


# Priority ordering when sorting by priority — Postgres compares the
# enum's storage values alphabetically ("high" < "low" < "med"), which
# isn't the human ordering. CASE-coerce to a numeric rank so high tasks
# surface first.
_PRIORITY_RANK = case(
    {
        TaskPriority.high: 1,
        TaskPriority.med: 2,
        TaskPriority.low: 3,
    },
    value=Task.priority,
)


def _apply_task_filters(
    stmt,
    *,
    status_filter: TaskStatus | None,
    priority: TaskPriority | None,
    q: str | None,
    due_filter: DueFilter | None,
    sort_by: SortBy,
    sort_dir: SortDir,
):
    """Compose the shared WHERE + ORDER clauses for `/tasks/me` and `/tasks/all`."""
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    if due_filter == "today":
        stmt = stmt.where(
            Task.due_at.is_not(None),
            func.date(Task.due_at) == func.current_date(),
        )
    elif due_filter == "overdue":
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at < func.now())
    elif due_filter == "upcoming":
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at > func.now())

    if sort_by == "priority":
        col = _PRIORITY_RANK
    elif sort_by == "title":
        col = Task.title
    elif sort_by == "created_at":
        col = Task.created_at
    elif sort_by == "last_activity_at":
        col = Task.last_activity_at
    else:
        col = Task.due_at

    ordered = col.asc() if sort_dir == "asc" else col.desc()
    if sort_by == "due_at":
        ordered = nulls_last(col.asc()) if sort_dir == "asc" else nulls_first(col.desc())
    elif sort_by == "last_activity_at":
        ordered = nulls_last(col.asc()) if sort_dir == "asc" else nulls_last(col.desc())

    return stmt.order_by(ordered, Task.created_at.desc())


_SNAPSHOT_FIELDS = (
    "id",
    "title",
    "description",
    "due_at",
    "assigned_to_id",
    "related_entity_type",
    "related_entity_id",
    "status",
    "priority",
    "followup_type",
    "custom_data",
)


def _snapshot(t: Task) -> dict[str, Any]:
    return snapshot(t, fields=_SNAPSHOT_FIELDS)


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    """Return a single task, scoped to the active tenant."""
    return await _da.get_task_by_id(session, task_id)


async def create_task(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: TaskCreate,
) -> Task:
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_TASK_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
    )
    task = Task(
        org_id=org_id,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        assigned_to_id=payload.assigned_to_id or current_user_id,
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
        priority=payload.priority,
        followup_type=payload.followup_type,
        status=TaskStatus.open,
        custom_data=cleaned_custom,
    )
    _da.insert_task(session, task)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.created",
        entity_type="task",
        entity_id=task.id,
        after=_snapshot(task),
    )
    return task


async def update_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    payload: TaskUpdate,
) -> Task:
    task = ensure_found(await get_task(session, task_id), entity="task")

    before = _snapshot(task)
    changes = payload.model_dump(exclude_unset=True)
    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_TASK_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    for key, value in changes.items():
        setattr(task, key, value)
    # Bump `last_activity_at` independently of the activity-insert
    # hook — not every task PATCH writes an activity (a title fix
    # doesn't, for instance), but the user still expects "recent
    # activity" to surface the edit.
    task.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.updated",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after=_snapshot(task),
    )
    return task


async def mark_task_missed(
    session: AsyncSession, *, task_id: uuid.UUID
) -> Task:
    """Flip a task from ``open`` → ``missed``.

    Terminal-status transitions are refused with 409 so a stale click
    on a follow-up already closed (either completed or previously
    marked missed) doesn't overwrite history. ``cancelled`` is also
    refused — a rep who cancelled a task shouldn't have it silently
    re-labelled as missed by a race.

    Emits ``tasks.marked_missed`` audit so the linked contact's
    timeline records why the follow-up stopped.
    """
    task = ensure_found(await get_task(session, task_id), entity="task")

    if task.status != TaskStatus.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Task is {task.status.value}; only open tasks can be marked missed."
            ),
        )

    before = _snapshot(task)
    task.status = TaskStatus.missed
    task.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.marked_missed",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after=_snapshot(task),
    )
    return task


async def delete_task(session: AsyncSession, *, task_id: uuid.UUID) -> None:
    task = ensure_found(await get_task(session, task_id), entity="task")
    before = _snapshot(task)
    task_uuid = task.id
    await _da.delete_task_row(session, task)
    await session.commit()

    await log_entity_change(
        action="tasks.deleted",
        entity_type="task",
        entity_id=task_uuid,
        before=before,
    )


async def list_tasks_for_entity(
    session: AsyncSession,
    *,
    related_entity_type: str,
    related_entity_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Tasks attached to one entity, latest-due first (with overdue at top)."""
    return await _da.list_tasks_for_entity_query(
        session,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        status_filter=status_filter,
        page=page,
        size=size,
    )


async def list_my_tasks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    q: str | None = None,
    due_filter: DueFilter | None = None,
    sort_by: SortBy = "due_at",
    sort_dir: SortDir = "asc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Caller's tasks. Filters mirror `/tasks/all`."""
    base = select(Task).where(Task.assigned_to_id == user_id)
    base = _apply_task_filters(
        base,
        status_filter=status_filter,
        priority=priority,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return await _da.paginate_tasks_select(session, base, page=page, size=size)


async def list_all_in_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assigned_to_id: uuid.UUID | None = None,
    q: str | None = None,
    due_filter: DueFilter | None = None,
    sort_by: SortBy = "due_at",
    sort_dir: SortDir = "asc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Every task in the org — gated by `users.read` at the router layer."""
    base = select(Task).where(Task.org_id == org_id)
    if assigned_to_id is not None:
        base = base.where(Task.assigned_to_id == assigned_to_id)
    base = _apply_task_filters(
        base,
        status_filter=status_filter,
        priority=priority,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return await _da.paginate_tasks_select(session, base, page=page, size=size)


# --- Bulk actions ----------------------------------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org."""
    if not await _da.user_has_active_membership(session, org_id=org_id, user_uuid=user_uuid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def bulk_reassign_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Bulk reassign. Tasks require an owner (the column is NOT NULL),
    so `None` is rejected with 422 even though the schema typing is
    optional. Rows already owned by the target are skipped (no-op,
    not an error).

    Batched hydrate (``list_tasks_by_ids_in_org``) replaces the prior
    per-id ``get_task`` loop, and every touched row now emits a
    ``tasks.reassigned`` audit entry to match the single-row path —
    bulk previously wrote timeline Activities but no audit trail."""
    if assigned_to_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tasks require an owner; assigned_to_id cannot be null",
        )
    await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    # One SELECT for the whole batch; the DAL enforces org_id.
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)

    # Collect per-row before/after snapshots so we can write audit
    # entries AFTER commit — a subscriber crash mid-loop then can't
    # roll back a whole reassign batch.
    reassigned = 0
    audit_batch: list[tuple[uuid.UUID, dict[str, Any], dict[str, Any]]] = []
    for task in tasks:
        if task.assigned_to_id == assigned_to_id:
            continue
        before_id = task.assigned_to_id
        before_snap = snapshot(task)
        task.assigned_to_id = assigned_to_id
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type="task",
            entity_id=task.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
            user_id=actor_user_id,
        )
        audit_batch.append((task.id, before_snap, snapshot(task)))
        reassigned += 1

    await session.commit()

    for task_id, before_snap, after_snap in audit_batch:
        await log_entity_change(
            action="tasks.reassigned",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
            after=after_snap,
        )
    return reassigned


async def bulk_mark_done_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> tuple[int, int]:
    """Move every open (or cancelled) task in the batch to ``done``.

    Batched hydrate replaces the prior per-id ``get_task`` loop, and
    every flipped row now emits a ``tasks.marked_done`` audit entry —
    the single-row PATCH path calls ``tasks.updated`` with before/after
    snapshots; bulk was previously silent, so subscribers listening
    for task completion (e.g. workflow triggers) never saw bulk-done
    events."""
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)

    done = 0
    skipped = 0
    audit_batch: list[tuple[uuid.UUID, dict[str, Any], dict[str, Any]]] = []
    for task in tasks:
        if task.status == TaskStatus.done:
            skipped += 1
            continue
        before_snap = snapshot(task)
        task.status = TaskStatus.done
        task.last_activity_at = datetime.now(UTC)
        audit_batch.append((task.id, before_snap, snapshot(task)))
        done += 1

    await session.commit()

    for task_id, before_snap, after_snap in audit_batch:
        await log_entity_change(
            action="tasks.marked_done",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
            after=after_snap,
        )
    return done, skipped


async def bulk_delete_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard delete in bulk. Single DELETE statement scoped by org_id
    so a misconfigured tenant context can't leak cross-org rows.

    Snapshots each row *before* the DELETE so we can write one
    ``tasks.deleted`` audit entry per gone row (matches the single-row
    ``delete_task`` path — the bulk path used to be silent, so any
    operator or subscriber replaying the audit trail would see rows
    vanish with no explanation).

    Tasks have no outbound FK RESTRICT dependents at the DB level so
    there is nothing to catch — leads.bulk_delete needs the
    IntegrityError wrap; tasks does not."""
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)
    snapshots = [(t.id, snapshot(t)) for t in tasks]

    rowcount = await _da.bulk_delete_tasks_by_ids(session, ids=ids, org_id=org_id)
    await session.commit()

    for task_id, before_snap in snapshots:
        await log_entity_change(
            action="tasks.deleted",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
        )
    return rowcount


# Re-export enums so callers get a stable import path through this module.
__all__ = [
    "DueFilter",
    "SortBy",
    "SortDir",
    "TaskPriority",
    "TaskStatus",
    "bulk_delete_tasks",
    "bulk_mark_done_tasks",
    "bulk_reassign_tasks",
    "create_task",
    "delete_task",
    "get_task",
    "list_all_in_org",
    "list_my_tasks",
    "list_tasks_for_entity",
    "update_task",
]
