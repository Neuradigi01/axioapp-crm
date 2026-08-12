"""HTTP routes for the tasks module.

  GET    /api/v1/tasks?related_entity_type=&related_entity_id=&status=
  GET    /api/v1/tasks/me?status=open&priority=&q=&due_filter=&sort_by=&sort_dir=
  GET    /api/v1/tasks/all?…  — same filters + assigned_to_id; gated on users.read
  POST   /api/v1/tasks
  GET    /api/v1/tasks/{id}
  PATCH  /api/v1/tasks/{id}
  DELETE /api/v1/tasks/{id}

`/tasks/me` and `/tasks/all` are declared before `/tasks/{id}` so
FastAPI's path-router treats "me" / "all" as literal segments, not as
UUIDs. Reads need `tasks.read`; the org-wide `/all` additionally needs
`users.read`. Writes need `tasks.write`. Tenant scoping is automatic.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.permissions.service import role_has_permission
from src.app.core.tasks.models import TaskPriority, TaskStatus
from src.app.core.tasks.schemas import (
    TaskBulkDelete,
    TaskBulkDeleteResult,
    TaskBulkMarkDone,
    TaskBulkMarkDoneResult,
    TaskBulkReassign,
    TaskBulkReassignResult,
    TaskCreate,
    TaskListResponse,
    TaskOut,
    TaskUpdate,
)
from src.app.core.tasks.service import (
    DueFilter,
    SortBy,
    SortDir,
    bulk_delete_tasks,
    bulk_mark_done_tasks,
    bulk_reassign_tasks,
    create_task,
    delete_task,
    get_task,
    list_all_in_org,
    list_my_tasks,
    list_tasks_for_entity,
    mark_task_missed,
    update_task,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/me", response_model=TaskListResponse)
async def my_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    priority: TaskPriority | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=255),
    due_filter: DueFilter | None = Query(default=None),
    sort_by: SortBy = Query(default="due_at"),
    sort_dir: SortDir = Query(default="asc"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.read")),
) -> TaskListResponse:
    rows, total = await list_my_tasks(
        db,
        user_id=user.legacy_uuid,
        status_filter=status_filter,
        priority=priority,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return TaskListResponse(
        items=[TaskOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/all", response_model=TaskListResponse)
async def all_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    priority: TaskPriority | None = Query(default=None),
    assigned_to_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=255),
    due_filter: DueFilter | None = Query(default=None),
    sort_by: SortBy = Query(default="due_at"),
    sort_dir: SortDir = Query(default="asc"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("users.read")),
) -> TaskListResponse:
    rows, total = await list_all_in_org(
        db,
        org_id=user.org_id,
        status_filter=status_filter,
        priority=priority,
        assigned_to_id=assigned_to_id,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return TaskListResponse(
        items=[TaskOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks_endpoint(
    related_entity_type: str = Query(..., min_length=1, max_length=64),
    related_entity_id: uuid.UUID = Query(...),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.read")),
) -> TaskListResponse:
    rows, total = await list_tasks_for_entity(
        db,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        status_filter=status_filter,
        page=page,
        size=size,
    )
    return TaskListResponse(
        items=[TaskOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.write")),
) -> TaskOut:
    # Only Owner / Admin / Sales Manager can delegate — everyone else
    # is self-assign only. The service enforces the rule; the router
    # just resolves the flag from the caller's role once.
    can_assign_others = await role_has_permission(db, user.role_id, "tasks.assign_others")
    task = await create_task(
        db,
        org_id=user.org_id,
        current_user_id=user.legacy_uuid,
        payload=payload,
        can_assign_others=can_assign_others,
    )
    return TaskOut.model_validate(task)


# --- Bulk-action endpoints --------------------------------------------------
#
# Declared before `/tasks/{task_id}` so FastAPI matches the literal
# segments (`bulk-reassign`, `bulk-mark-done`, `bulk-delete`) ahead of
# the UUID-typed dynamic segment.


@router.post("/bulk-reassign", response_model=TaskBulkReassignResult)
async def bulk_reassign_tasks_endpoint(
    payload: TaskBulkReassign,
    db: AsyncSession = Depends(get_db),
    # Reassigning is delegation by definition — Employee / Support Agent
    # don't get this power. Gated at the router with the same perm the
    # create + update flows check inside the service.
    user: User = Depends(require_permissions("tasks.assign_others")),
) -> TaskBulkReassignResult:
    n = await bulk_reassign_tasks(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return TaskBulkReassignResult(reassigned=n)


@router.post("/bulk-mark-done", response_model=TaskBulkMarkDoneResult)
async def bulk_mark_done_tasks_endpoint(
    payload: TaskBulkMarkDone,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.write")),
) -> TaskBulkMarkDoneResult:
    done, skipped = await bulk_mark_done_tasks(db, ids=payload.ids, org_id=user.org_id)
    return TaskBulkMarkDoneResult(done=done, skipped=skipped)


@router.post("/bulk-delete", response_model=TaskBulkDeleteResult)
async def bulk_delete_tasks_endpoint(
    payload: TaskBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.write")),
) -> TaskBulkDeleteResult:
    n = await bulk_delete_tasks(db, ids=payload.ids, org_id=user.org_id)
    return TaskBulkDeleteResult(deleted=n)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_endpoint(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.read")),
) -> TaskOut:
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_endpoint(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.write")),
) -> TaskOut:
    # PATCH that changes `assigned_to_id` to another user counts as a
    # delegation — same gate as create_task. Self-updates (title, due
    # date, status flips) work for anyone with tasks.write.
    can_assign_others = await role_has_permission(db, user.role_id, "tasks.assign_others")
    task = await update_task(
        db,
        task_id=task_id,
        payload=payload,
        current_user_id=user.legacy_uuid,
        can_assign_others=can_assign_others,
    )
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.write")),
) -> Response:
    await delete_task(db, task_id=task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/mark-missed", response_model=TaskOut)
async def mark_task_missed_endpoint(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.write")),
) -> TaskOut:
    """Flip an open task to ``missed`` (terminal). Returns the mutated
    row so the client can update its optimistic state with the real
    ``updated_at`` timestamp. Refuses transitions from ``done`` /
    ``missed`` / ``cancelled`` with 409."""
    task = await mark_task_missed(db, task_id=task_id)
    return TaskOut.model_validate(task)
