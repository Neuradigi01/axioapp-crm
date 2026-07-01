"""ORM binding for the per-user Google Calendar OAuth token store.

One row per ``(org_id, user_id)``. Fernet-encrypted refresh token +
short-lived cached access token + connection status metadata.

Tokens (``refresh_token_encrypted`` / ``access_token_encrypted``) are
opaque ciphertext to everything except
:mod:`core.integrations.google_calendar.oauth` (Step 2) which is the
sole holder of the encryption key + the sole decrypt call site. No
router / no service returns them plaintext to the API surface.

Tenant-scoped via the :class:`TenantScoped` mixin — the ORM tenant
filter auto-applies to every query. The migration
(``0147_google_calendar_tokens``) additionally installs a Postgres
RLS policy so raw SQL / superuser sessions also honour the isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class GoogleCalendarToken(Base, TenantScoped):
    """One employee's connected Google Calendar credentials.

    The ``UNIQUE (org_id, user_id)`` constraint from the migration
    enforces the one-active-connection-per-user rule; when the operator
    reconnects (after a revoke) the service layer UPDATEs the existing
    row rather than inserting a duplicate.
    """

    __tablename__ = "tbl_user_google_calendar_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Matches the tbl_organization_members convention: users are keyed
    # on BIGINT ``tbl_user_login.id`` at the DB layer. The FurnitureCRM
    # ORM stub declares ``User.id`` as UUID via SQLAlchemy metadata
    # tricks but every actual FK in the codebase uses BIGINT here.
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tbl_user_login.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Display label on the integrations card ("Connected as ajay@gmail.com").
    google_email: Mapped[str] = mapped_column(Text, nullable=False)
    # Google's stable `sub` claim — never changes across reconnects.
    # Used as the join key when we cross-reference back to Google.
    google_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Fernet ciphertexts. refresh_token is REQUIRED (Google's `access_type=
    # offline` + `prompt=consent` in the authorize URL guarantees it on
    # first grant); without it we can't refresh the access token so the
    # connection is functionally dead.
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What the user actually approved. Google may return fewer scopes
    # than we requested if the user unticks any. We surface the diff on
    # the integrations card so the operator knows why sync isn't working
    # (e.g. "You granted openid + email but not calendar.events — reconnect
    # and approve calendar access").
    scopes_granted: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::text[]"),
    )
    # Populated on first successful sync via `calendarList/primary`.
    # Usually equal to ``google_email`` but stored explicitly so we
    # never have to guess for aliased / delegated accounts.
    primary_calendar_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'active' | 'revoked' | 'error' | 'expired'.
    #   * active   — happy path, tokens usable.
    #   * revoked  — refresh call returned ``invalid_grant``. User must
    #                reconnect via the integrations card.
    #   * error    — most recent API call failed for a non-token reason
    #                (rate limit, transient 5xx). Retryable.
    #   * expired  — access token expired + refresh not yet attempted
    #                (transient state; usually never persisted).
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
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


__all__ = ["GoogleCalendarToken"]
