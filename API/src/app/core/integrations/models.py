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

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    # Per-integration webhook URL discriminator. Random 32-byte
    # url-safe token generated on first connect, rotated on every
    # reconnect. Google + Meta receive the full webhook URL with this
    # token in the path; disconnect nulls the secret so stale URLs
    # immediately stop authenticating. Migration 0049 adds the
    # partial-UNIQUE index for the path-lookup query.
    webhook_secret: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    @property
    def is_connected(self) -> bool:
        return self.status == IntegrationStatus.connected


class IntegrationSubscription(Base, TenantScoped):
    """One row per (integration, ad-platform form) — the bridge between
    a Google Lead Form (or Meta Lead Ad form, Step 5) and the field
    mapping the worker uses when translating an inbound payload into
    a CRM contact + lead.

    `field_mapping` is `{ad_field_name: "contact.full_name"}` /
    `"contact.phone"` / `"contact.email"` / `"custom_data.<key>"` —
    same target shape as the bulk-import mapping registry, reused for
    consistency. An ad-side field absent from the mapping is dropped.

    `enabled=false` is the soft-pause: the worker DLQs payloads for
    disabled subscriptions instead of silently dropping them, so a
    later re-enable + replay catches up the missed deliveries."""

    __tablename__ = "integration_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_form_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_form_label: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    field_mapping: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class IntegrationDLQ(Base, TenantScoped):
    """Dead-letter row for payloads that exhausted the Celery retry
    policy or that were rejected upfront (no subscription, integration
    disconnected, etc.). The Settings UI lists these by (provider,
    created_at desc) and exposes a replay button — `replayed_at` /
    `replayed_by` flip when an Owner re-enqueues an entry.

    `integration_id` is nullable so a hard-deleted integration leaves
    its DLQ rows queryable for forensics — Step 1's `disconnect` just
    nulls tokens; an actual row-delete would only happen later if/when
    we add an "archive integration" surface, and we don't want DLQ to
    cascade away in that case (`ON DELETE SET NULL`)."""

    __tablename__ = "integration_dlq"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="SET NULL"),
        nullable=True,
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
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retries_attempted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    replayed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replayed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


__all__ = [
    "Integration",
    "IntegrationDLQ",
    "IntegrationProvider",
    "IntegrationStatus",
    "IntegrationSubscription",
]
