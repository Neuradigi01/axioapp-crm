"""HTTP routes for the tasks module.

  GET    /api/v1/tasks?related_entity_type=&related_entity_id=&status=
  GET    /api/v1/tasks/me?status=open
  POST   /api/v1/tasks
  GET    /api/v1/tasks/{id}
  PATCH  /api/v1/tasks/{id}
  DELETE /api/v1/tasks/{id}

`/tasks/me` is declared before `/tasks/{id}` so FastAPI's path-router
treats "me" as a literal segment, not a UUID. Reads need `tasks.read`,
writes need `tasks.write`. Tenant scoping is automatic.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.tasks.models import TaskStatus
from src.app.core.tasks.schemas import (
    TaskCreate,
    TaskListResponse,
    TaskOut,
    TaskUpdate,
)
from src.app.core.tasks.service import (
    create_task,
    delete_task,
    get_task,
    list_my_tasks,
    list_tasks_for_entity,
    update_task,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/me", response_model=TaskListResponse)
async def my_tasks(
    status_filter: Optional[TaskStatus] = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("tasks.read")),
) -> TaskListResponse:
    rows, total = await list_my_tasks(
        db, user_id=user.legacy_uuid, status_filter=status_filter, page=page, size=size
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
    status_filter: Optional[TaskStatus] = Query(default=None, alias="status"),
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
    task = await create_task(
        db, org_id=user.org_id, current_user_id=user.legacy_uuid, payload=payload
    )
    return TaskOut.model_validate(task)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_endpoint(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.read")),
) -> TaskOut:
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="task not found"
        )
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task_endpoint(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.write")),
) -> TaskOut:
    task = await update_task(db, task_id=task_id, payload=payload)
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("tasks.write")),
) -> Response:
    await delete_task(db, task_id=task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
