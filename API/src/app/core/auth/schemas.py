"""Pydantic v2 request/response shapes for the auth router."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Plain str (not EmailStr): the step spec uses `admin@demo.local`, which
    # RFC 6761 reserves and EmailStr rejects. Login does not need strict
    # email validation — the actual check is DB row match.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    # Optional — when omitted, the server resolves the user's org from the
    # email via the active `tbl_organization_members` row. Used by the demo
    # pill (which sends an explicit slug) and by manual login (which doesn't).
    org_slug: str | None = Field(default=None, min_length=1, max_length=64)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


class RefreshResponse(LoginResponse):
    """Same shape as LoginResponse — the new rotated JWT."""


class LogoutResponse(BaseModel):
    success: bool = True


class RegisterRequest(BaseModel):
    """Body for the layered self-signup endpoint.

    `organization_name` is optional — the server falls back to
    `"<first_name>'s Workspace"` if blank or omitted. EmailStr is
    intentionally avoided to match the LoginRequest decision (local
    `.local` TLDs must be representable in dev).
    """
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    organization_name: str | None = Field(default=None, max_length=128)


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    organization_id: uuid.UUID
    organization_slug: str
    role_name: str
