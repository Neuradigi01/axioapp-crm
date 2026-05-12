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
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.tasks.models import Task, TaskPriority, TaskStatus
from src.app.core.tasks.schemas import TaskCreate, TaskUpdate


def _snapshot(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "due_at": t.due_at.isoformat() if t.due_at is not None else None,
        "assigned_to_id": str(t.assigned_to_id),
        "related_entity_type": t.related_entity_type,
        "related_entity_id": (
            str(t.related_entity_id) if t.related_entity_id is not None else None
        ),
        "status": t.status.value,
        "priority": t.priority.value,
    }


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Optional[Task]:
    """Return a single task, scoped to the active tenant."""
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def create_task(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: TaskCreate,
) -> Task:
    task = Task(
        org_id=org_id,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        assigned_to_id=payload.assigned_to_id or current_user_id,
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
        priority=payload.priority,
        status=TaskStatus.open,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    await audit.log(
        "tasks.created",
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
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="task not found"
        )

    before = _snapshot(task)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(task, key, value)
    await session.commit()
    await session.refresh(task)

    await audit.log(
        "tasks.updated",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after=_snapshot(task),
    )
    return task


async def delete_task(session: AsyncSession, *, task_id: uuid.UUID) -> None:
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="task not found"
        )
    before = _snapshot(task)
    task_uuid = task.id
    await session.delete(task)
    await session.commit()

    await audit.log(
        "tasks.deleted",
        entity_type="task",
        entity_id=task_uuid,
        before=before,
    )


async def list_tasks_for_entity(
    session: AsyncSession,
    *,
    related_entity_type: str,
    related_entity_id: uuid.UUID,
    status_filter: Optional[TaskStatus] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Tasks attached to one entity, latest-due first (with overdue at top).

    `status_filter` lets the UI request only open tasks for the panel's
    headline, or all tasks for the full history. Sort order favours the
    "what needs my attention now" mental model: earliest due_at first,
    nulls last (no due date).
    """
    filters: list[Any] = [
        Task.related_entity_type == related_entity_type,
        Task.related_entity_id == related_entity_id,
    ]
    if status_filter is not None:
        filters.append(Task.status == status_filter)

    base = (
        select(Task)
        .where(*filters)
        .order_by(nulls_last(Task.due_at.asc()), Task.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(Task).where(*filters)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


async def list_my_tasks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    status_filter: Optional[TaskStatus] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Caller's tasks, earliest-due first. Backs the header popover."""
    filters: list[Any] = [Task.assigned_to_id == user_id]
    if status_filter is not None:
        filters.append(Task.status == status_filter)

    base = (
        select(Task)
        .where(*filters)
        .order_by(nulls_last(Task.due_at.asc()), Task.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(Task).where(*filters)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


# Re-export enums so callers get a stable import path through this module.
__all__ = [
    "TaskPriority",
    "TaskStatus",
    "create_task",
    "delete_task",
    "get_task",
    "list_my_tasks",
    "list_tasks_for_entity",
    "update_task",
]
