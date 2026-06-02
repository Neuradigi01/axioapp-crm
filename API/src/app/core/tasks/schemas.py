"""Pydantic v2 schemas for the tasks module.

`assigned_to_id` is optional on create: when omitted, the service
assigns the task to the caller. `related_entity_type` and
`related_entity_id` are paired — both or neither must be present —
because a "task on contact X" needs both halves to be a meaningful row.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.tasks.models import TaskPriority, TaskStatus
from src.app.shared.schemas import ORMModel, PaginatedResponse


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    assigned_to_id: Optional[uuid.UUID] = None
    related_entity_type: Optional[str] = Field(default=None, max_length=64)
    related_entity_id: Optional[uuid.UUID] = None
    priority: TaskPriority = TaskPriority.med

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_relation_pair(self) -> "TaskCreate":
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError(
                "related_entity_type and related_entity_id must be set together "
                "(or both left null)"
            )
        return self


class TaskUpdate(BaseModel):
    """Every field optional — partial PATCH."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    assigned_to_id: Optional[uuid.UUID] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class TaskOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    description: Optional[str]
    due_at: Optional[datetime]
    assigned_to_id: uuid.UUID
    related_entity_type: Optional[str]
    related_entity_id: Optional[uuid.UUID]
    status: TaskStatus
    priority: TaskPriority
    last_activity_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


TaskListResponse = PaginatedResponse[TaskOut]


# --- Bulk action shapes -----------------------------------------------------


class TaskBulkReassign(BaseModel):
    """Bulk reassign. Tasks require an owner (`assigned_to_id NOT NULL`)
    so the service rejects `None`; the type stays optional here to
    match the cross-module schema shape but the service raises 422 if
    the caller actually sends null."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class TaskBulkMarkDone(BaseModel):
    """Bulk-mark-done. Rows already in `done` are skipped (counted as
    `skipped`) — same partial-success semantic as appointments
    bulk-cancel."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class TaskBulkDelete(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class TaskBulkReassignResult(BaseModel):
    reassigned: int


class TaskBulkMarkDoneResult(BaseModel):
    """`done` counts rows newly transitioned. `skipped` counts rows
    already in `done`."""

    done: int
    skipped: int


class TaskBulkDeleteResult(BaseModel):
    deleted: int
