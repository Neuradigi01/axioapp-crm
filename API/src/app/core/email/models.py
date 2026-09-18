"""`EmailAccount` model — per-user OAuth-connected mailbox.

One row per `(user_id, provider, external_account_id)`. Tokens live
as Fernet ciphertexts under `core.integrations.crypto` (the same
encryption key as the ad-integrations track — no second key to
manage). `service.decrypt_tokens()` is the only path that pulls
plaintext, and only the provider-specific API clients call it.

`user_id` and `disconnected_by` are plain UUIDs (no FK) per the
post-0037 convention — the legacy `users` table is on soak and FKs
to it are forbidden in new work. The UUID is the user's
`legacy_uuid` on `tbl_user_login`.

Tenant-scoped: standard `TenantScoped` mixin + RLS policy from
migration 0082. The ORM tenant filter auto-applies to every query.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmailAccountProvider(str, enum.Enum):
    """Which mailbox provider this account speaks to. Postgres enum
    `email_account_provider` from migration 0082. v1 ships Gmail +
    Microsoft 365 — IMAP/SMTP fallback is a v2 surface."""

    gmail = "gmail"
    microsoft = "microsoft"


class EmailAccountSyncState(str, enum.Enum):
    """Sync lifecycle. Postgres enum `email_account_sync_state` from
    migration 0082.

      - `pending`: connect callback just landed; backfill not yet
        enqueued. Transient state, usually flips to `backfilling`
        within seconds.
      - `backfilling`: Step 4's daemon is loading the initial
        30-day history. UI shows a pulsing "Backfilling…" pill.
      - `live`: incremental sync is current; push webhooks +
        60-second poll fallback are the steady-state cadence.
      - `error`: most recent sync attempt failed; see
        `last_sync_error`. Daemon falls back to hourly retry.
      - `disconnected`: the rep (or Owner via the admin scope)
        revoked the connection; tokens are nulled. Row preserved
        for history.
    """

    pending = "pending"
    backfilling = "backfilling"
    live = "live"
    error = "error"
    disconnected = "disconnected"


class EmailAccount(Base, TenantScoped):
    """One row per (user, provider, external_account_id). A rep can
    connect both a Gmail and a Microsoft account, or two distinct
    Gmail accounts — the UNIQUE constraint only stops reconnecting
    the *same* external account twice."""

    __tablename__ = "tbl_email_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[EmailAccountProvider] = mapped_column(
        Enum(
            EmailAccountProvider,
            name="email_account_provider",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    external_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    email_address: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Fernet ciphertexts. NULL when sync_state='disconnected' — the
    # row stays so connect/disconnect history survives reconnects.
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes_granted: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_state: Mapped[EmailAccountSyncState] = mapped_column(
        Enum(
            EmailAccountSyncState,
            name="email_account_sync_state",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    daily_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    daily_sent_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # `is_default=True` marks this mailbox as the org's outbound sender
    # for automations, workflows, templates, and conversation replies.
    # Enforced at the service layer alongside `EmailSmtpSender.is_default`
    # so exactly one row across BOTH tables holds the flag per org — see
    # `email_senders.service.set_default_sender`. Auto-demoted on
    # `disconnect()` so a revoked grant can't stay wired as the default.
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    @property
    def is_connected(self) -> bool:
        return (
            self.sync_state not in (EmailAccountSyncState.disconnected,)
            and self.access_token_enc is not None
        )


__all__ = [
    "EmailAccount",
    "EmailAccountProvider",
    "EmailAccountSyncState",
]
