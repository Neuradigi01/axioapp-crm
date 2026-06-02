"""Pydantic v2 schemas for the tenants module."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

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
