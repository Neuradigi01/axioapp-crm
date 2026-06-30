"""Pydantic v2 schemas for the tenants module."""

from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel


class OwnershipTransferRequest(BaseModel):
    """Body of POST /api/v1/ownership/transfer.

    `target_user_id` is the UUID identity of the recipient (what
    `/api/v1/users` returns under `id` — i.e. `tbl_user_login.legacy_uuid`).
    `demote_to_role_id` is optional; defaults to the org's Admin role.
    """

    target_user_id: uuid.UUID
    demote_to_role_id: uuid.UUID | None = Field(default=None)


class OrganizationMemberOut(ORMModel):
    id: int
    organization_id: uuid.UUID
    user_member_id: int
    role_id: uuid.UUID
    is_active: bool


class OwnershipTransferResponse(BaseModel):
    new_owner: OrganizationMemberOut
    demoted: OrganizationMemberOut


# --- Step-13 send-rule compliance settings -------------------------------


class SendRulesOut(BaseModel):
    """Read shape for ``GET /api/v1/tenants/send-rules`` — the
    Step-13 send-guard configuration that gates marketing-category
    automation runs."""

    model_config = ConfigDict(from_attributes=True)

    quiet_hours_start: time
    quiet_hours_end: time
    quiet_hours_timezone: str
    marketing_frequency_cap_per_week: int
    marketing_frequency_cap_enabled: bool


class SendRulesUpdate(BaseModel):
    """Whitelisted patch payload for ``PATCH /api/v1/tenants/send-rules``.

    All fields optional; unset keys retain the org's prior value.
    The Settings UI's "Send rules" tab POSTs the full form so unset
    keys are rare, but the schema is permissive so a future UI can
    twiddle one knob at a time.
    """

    model_config = ConfigDict(extra="forbid")

    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    quiet_hours_timezone: str | None = Field(default=None, max_length=64)
    marketing_frequency_cap_per_week: int | None = Field(default=None, ge=0, le=100)
    marketing_frequency_cap_enabled: bool | None = None
