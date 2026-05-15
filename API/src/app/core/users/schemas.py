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
