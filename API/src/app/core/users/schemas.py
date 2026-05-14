"""Pydantic v2 schemas for users.

`UserOut` is the standard read shape for admin listings.
`UserMe` extends it with the role + permission keys so the frontend
can render gated UI from a single `/users/me` round-trip.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
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
