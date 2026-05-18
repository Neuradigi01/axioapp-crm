"""Pydantic v2 schemas for users.

`UserOut` is the standard read shape for admin listings.
`UserMe` extends it with the role + permission keys so the frontend
can render gated UI from a single `/users/me` round-trip.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    # `populate_by_name=True` so callers passing `id=...` explicitly
    # still work alongside the `validation_alias` below that pulls from
    # `User.legacy_uuid` when `model_validate(user)` reads off the ORM
    # instance. (After DR.6.3 `User.id` is the bigint storage PK; the
    # UUID identity exposed to API consumers is `User.legacy_uuid`.)
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID = Field(validation_alias="legacy_uuid")
    org_id: uuid.UUID
    # Plain str (not EmailStr): seed uses `admin@demo.local`, which RFC 6761
    # reserves and EmailStr rejects on serialise. Strict email validation
    # lives at create/update boundaries, not on read.
    email: str
    full_name: str
    phone: str | None
    role_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrgSummary(BaseModel):
    """Compact org identity included in `/users/me` so the SPA can
    brand its shell (sidebar header, etc.) per current tenant without
    a second round-trip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    pack_id: str


class UserMe(UserOut):
    role_name: str
    permission_keys: list[str]
    org: OrgSummary


class UserCreate(BaseModel):
    """Admin creates a new user in the caller's org.

    Password is not set here — the user is unable to log in until they
    accept an invitation (step 2.5.6). A random placeholder password
    is written so the bcrypt verify never short-circuits NULL.
    """

    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_id: uuid.UUID


class UserUpdate(BaseModel):
    """Admin updates a user's display name, phone, or role.

    Email is immutable — changing email means inviting a new account.
    Status (is_active) goes through a separate endpoint so the audit
    trail is unambiguous.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_id: uuid.UUID | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class MeUpdate(BaseModel):
    """Self-service profile update — name + phone only.

    Email is immutable; changing it = inviting a new account. Role and
    org-membership state are admin-only and stay out of this shape.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=255)
    sign_out_others: bool = False
