"""Pydantic v2 schemas for users.

`UserOut` is the standard read shape for admin listings.
`UserMe` extends it with the role + permission keys so the frontend
can render gated UI from a single `/users/me` round-trip.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str | None
    role_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserMe(UserOut):
    role_name: str
    permission_keys: list[str]
