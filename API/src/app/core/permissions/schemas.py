"""Pydantic v2 schemas for roles and permissions."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    description: str | None
    module: str


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    is_system: bool
    created_at: datetime


class RoleWithCounts(RoleOut):
    """Role row + computed counts + the grant set.

    `permission_count` and `member_count` drive the roles-management
    list view (e.g. "Admin · 44 permissions · 1 member"). The
    `permission_keys` list is the actual grant set — the editor reads
    it to pre-check the boxes when the user opens an existing role
    for edit. Computed via `array_agg` in `list_roles_in_org` so no
    N+1 lookups when listing a dozen roles per org.
    """

    permission_count: int
    member_count: int
    permission_keys: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    permission_keys: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    """At least one of `name` or `permission_keys` should be set."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    permission_keys: list[str] | None = None
