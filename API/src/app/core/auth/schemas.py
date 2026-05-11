"""Pydantic v2 request/response shapes for the auth router."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Plain str (not EmailStr): the step spec uses `admin@demo.local`, which
    # RFC 6761 reserves and EmailStr rejects. Login does not need strict
    # email validation — the actual check is DB row match.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    org_slug: str = Field(min_length=1, max_length=64)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


class RefreshResponse(LoginResponse):
    """Same shape as LoginResponse — the new rotated JWT."""


class LogoutResponse(BaseModel):
    success: bool = True
