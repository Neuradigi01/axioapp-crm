"""Pydantic v2 schemas for the staff-portal auth surface.

`StaffPickerUser` is the public-within-the-org shape exposed by
`GET /staff-portal/users`. It deliberately excludes email/phone/PIN
hash so a tablet sitting in the shop floor can't leak PII.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.app.shared.schemas import ORMModel


class StaffPickerUser(ORMModel):
    """One row in the login picker. Only safe-to-show fields."""

    id: uuid.UUID
    full_name: str
    # `avatar` is a placeholder until file storage / avatar uploads land
    # in Phase 5 — kept here so the tablet UI can render an `<img>`
    # without re-shaping when avatars arrive.
    avatar: str | None = None


class StaffLoginPayload(BaseModel):
    org_slug: str = Field(min_length=1, max_length=64)
    user_id: uuid.UUID
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class StaffLoginResponse(BaseModel):
    staff_token: str
    expires_at: datetime
    user_id: uuid.UUID
    org_id: uuid.UUID


class StaffMeOut(BaseModel):
    """Minimal `who am I` for the tablet header / dashboard greeting."""

    id: uuid.UUID
    org_id: uuid.UUID
    full_name: str
    email: str
