"""Pydantic v2 schemas for the email-accounts API surface.

`EmailAccountRead` is the public projection — **deliberately omits
the `*_enc` ciphertext columns** so tokens cannot leak via the API
even if a caller bypasses the router and serialises the SQLAlchemy
row directly.

`EmailAccountUpsert` is the internal write shape — used by the
OAuth callback handlers (Steps 2 + 3) to pass plaintext tokens into
`service.upsert()`. It is NEVER deserialised from an HTTP body; the
router has no POST/PUT endpoint that accepts it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.app.shared.schemas import ORMModel


EmailAccountProviderLiteral = Literal["gmail", "microsoft"]
EmailAccountSyncStateLiteral = Literal[
    "pending", "backfilling", "live", "error", "disconnected"
]


class EmailAccountRead(ORMModel):
    """Row projection for `GET /api/v1/email/accounts`. Encrypted-token
    columns (`access_token_enc`, `refresh_token_enc`) are intentionally
    absent from this shape — a router accidentally returning the raw
    ORM row cannot leak ciphertext through this schema."""

    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    provider: EmailAccountProviderLiteral
    external_account_id: str
    email_address: str
    display_name: Optional[str]
    token_expires_at: Optional[datetime]
    scopes_granted: list[str]
    sync_state: EmailAccountSyncStateLiteral
    last_sync_at: Optional[datetime]
    last_sync_error: Optional[str]
    daily_sent_count: int
    daily_sent_reset_at: datetime
    connected_at: datetime
    disconnected_at: Optional[datetime]
    disconnected_by: Optional[uuid.UUID]


class EmailAccountUpsert(BaseModel):
    """Internal write shape — passed from the OAuth callback handlers
    (Steps 2 + 3) into `service.upsert()`. NOT exposed as an HTTP
    request body. Plaintext tokens come straight out of the OAuth
    exchange; ciphertext is what hits Postgres."""

    provider: EmailAccountProviderLiteral
    external_account_id: str = Field(min_length=1, max_length=255)
    email_address: str = Field(min_length=3, max_length=320)
    display_name: Optional[str] = Field(default=None, max_length=255)
    access_token: str = Field(min_length=1)
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes_granted: list[str] = Field(default_factory=list)


__all__ = [
    "EmailAccountProviderLiteral",
    "EmailAccountRead",
    "EmailAccountSyncStateLiteral",
    "EmailAccountUpsert",
]
