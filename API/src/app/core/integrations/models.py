"""`Integration` model — per-org OAuth credential storage for ad
platforms (Google Ads + Meta Ads in v1; future providers slot in by
extending the `IntegrationProvider` enum).

Tokens (`access_token_enc`, `refresh_token_enc`) live as Fernet
ciphertext. They're decrypted ONLY by `core/integrations/service.py`'s
`decrypt_tokens()`, which is itself called only by the provider-
specific code that needs to make API calls — never by anything that
returns data to the API surface.

`connected_by` / `disconnected_by` are plain UUIDs (no FK) per the
post-0037 convention.

Tenant-scoped: standard `TenantScoped` mixin + RLS policy from the
migration. The ORM tenant filter auto-applies to every query.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class IntegrationProvider(str, enum.Enum):
    """Which ad platform this integration speaks to. Postgres enum
    `integration_provider` from migration 0048."""

    google_ads = "google_ads"
    meta_ads = "meta_ads"


class IntegrationStatus(str, enum.Enum):
    """Lifecycle state of the connection. Postgres enum
    `integration_status` from migration 0048.

      - `connected`: tokens present + within `token_expires_at`.
      - `disconnected`: Owner clicked Disconnect (tokens nulled).
      - `expired`: refresh attempt failed; needs reconnect.
      - `error`: most recent provider call failed; see `last_error`.
    """

    connected = "connected"
    disconnected = "disconnected"
    expired = "expired"
    error = "error"


class Integration(Base, TenantScoped):
    """One row per `(org_id, provider)`. UNIQUE constraint enforces the
    one-account-per-provider-per-org rule for v1 — multi-account is a
    future surface."""

    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(
            IntegrationProvider,
            name="integration_provider",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    account_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_label: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # Fernet ciphertexts. NULL when status='disconnected'.
    access_token_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(
            IntegrationStatus,
            name="integration_status",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        server_default=text("'disconnected'"),
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disconnected_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    @property
    def is_connected(self) -> bool:
        return self.status == IntegrationStatus.connected


__all__ = ["Integration", "IntegrationProvider", "IntegrationStatus"]
