"""Pydantic v2 schemas for the tasks module.

`assigned_to_id` is optional on create: when omitted, the service
assigns the task to the caller. `related_entity_type` and
`related_entity_id` are paired — both or neither must be present —
because a "task on contact X" needs both halves to be a meaningful row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.tasks.models import TaskPriority, TaskStatus
from src.app.shared.schemas import (
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
    PaginatedResponse,
    TimestampedOrgScopedOut,
)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    assigned_to_id: uuid.UUID | None = None
    related_entity_type: str | None = Field(default=None, max_length=64)
    related_entity_id: uuid.UUID | None = None
    priority: TaskPriority = TaskPriority.med

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_relation_pair(self) -> TaskCreate:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError(
                "related_entity_type and related_entity_id must be set together (or both left null)"
            )
        return self


class TaskUpdate(BaseModel):
    """Every field optional — partial PATCH."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    assigned_to_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class TaskOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    title: str
    description: str | None
    due_at: datetime | None
    assigned_to_id: uuid.UUID
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    status: TaskStatus
    priority: TaskPriority
    last_activity_at: datetime | None


TaskListResponse = PaginatedResponse[TaskOut]


# --- Bulk action shapes -----------------------------------------------------


# `TaskBulkReassign.assigned_to_id` is optional in the wire shape (the
# shared `BulkReassign` matches every entity) but tasks require an owner
# at the DB level — the service layer raises 422 if the caller sends null.
TaskBulkReassign = BulkReassign


class TaskBulkMarkDone(BaseModel):
    """Bulk-mark-done. Rows already in `done` are skipped (counted as
    `skipped`) — same partial-success semantic as appointments
    bulk-cancel."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


TaskBulkDelete = BulkDelete

TaskBulkReassignResult = BulkReassignResult


class TaskBulkMarkDoneResult(BaseModel):
    """`done` counts rows newly transitioned. `skipped` counts rows
    already in `done`."""

    done: int
    skipped: int


TaskBulkDeleteResult = BulkDeleteResult
