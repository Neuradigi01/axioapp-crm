"""Pydantic v2 schemas for the integrations API surface.

`IntegrationRead` is the public projection — **deliberately omits the
`*_enc` ciphertext columns** so tokens cannot leak via the API even if
a caller bypasses the router and serialises the SQLAlchemy row directly.

`IntegrationUpsert` is the internal write shape — used by the OAuth
callback handlers (Step 2 + 4) to pass plaintext tokens into
`service.upsert()`. It's NEVER deserialised from an HTTP body; the
router has no PUT/POST endpoint that accepts it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Mirrors the SQLAlchemy `IntegrationProvider` / `IntegrationStatus`
# enums as Literals so schema consumers don't have to import the ORM.
IntegrationProviderLiteral = Literal["google_ads", "meta_ads"]
IntegrationStatusLiteral = Literal[
    "connected", "disconnected", "expired", "error"
]


class IntegrationRead(BaseModel):
    """Row projection for `GET /api/v1/integrations`. Tokens are
    intentionally absent — the `*_enc` columns from the ORM never
    surface here, even by accident, because they aren't declared."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    provider: IntegrationProviderLiteral
    account_id: Optional[str]
    account_label: Optional[str]
    token_expires_at: Optional[datetime]
    scopes: Optional[list[str]]
    status: IntegrationStatusLiteral
    last_error: Optional[str]
    connected_at: Optional[datetime]
    connected_by: Optional[uuid.UUID]
    disconnected_at: Optional[datetime]
    disconnected_by: Optional[uuid.UUID]
    updated_at: datetime


class IntegrationUpsert(BaseModel):
    """Internal write shape — passed from the OAuth callback handlers
    into `service.upsert()`. NOT exposed as an HTTP request body."""

    provider: IntegrationProviderLiteral
    account_id: Optional[str] = Field(default=None, max_length=128)
    account_label: Optional[str] = Field(default=None, max_length=255)
    access_token: str = Field(min_length=1)
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)


__all__ = [
    "IntegrationProviderLiteral",
    "IntegrationRead",
    "IntegrationStatusLiteral",
    "IntegrationUpsert",
]
