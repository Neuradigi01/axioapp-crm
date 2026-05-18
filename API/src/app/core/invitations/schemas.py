"""Pydantic v2 shapes for the invitations API."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InvitationCreate(BaseModel):
    """Admin issues an invitation."""

    email: str = Field(min_length=3, max_length=255)
    role_id: uuid.UUID


class InvitationOut(BaseModel):
    """Admin-side read shape — never includes the raw token."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role_id: uuid.UUID
    invited_by: uuid.UUID
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InvitationCreated(InvitationOut):
    """Returned only from POST /invitations.

    Includes the one-time `accept_link` so the admin UI can show a
    toast with the link (handy for dev / for the admin to share if
    the email never arrives). Subsequent GETs do NOT include it —
    the raw token is gone once the API response is sent.
    """

    accept_link: str


class InvitationLookup(BaseModel):
    """Unauthenticated lookup — what the accept page renders before
    the recipient sets their password."""

    email: str
    role_name: str
    org_name: str
    org_slug: str


class InvitationAccept(BaseModel):
    """Recipient redeems the invitation."""

    token: str = Field(min_length=8, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(default="", max_length=128)
    phone: str | None = Field(default=None, max_length=32)
