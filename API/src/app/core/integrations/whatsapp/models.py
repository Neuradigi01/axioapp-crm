"""ORM model for `whatsapp_account_configs` — WA-specific fields sidecar
to the generic `integrations` row.

Held outside `core/integrations/models.py` for the same reason
`MetaPageToken` is: keeping the parent `models.py` provider-agnostic so
a future channel (Telegram, SMS gateway, …) doesn't accrete columns on
the central table.

`app_secret_enc` is Fernet ciphertext — same encryption key
(`INTEGRATIONS_ENCRYPTION_KEY`) as the parent row's `access_token_enc`.
The plaintext is decrypted ONLY inside the WhatsApp webhook signature
verifier (Step 3.5.12).

The UNIQUE(integration_id) index enforces one config per integration —
multiple WhatsApp phone numbers per org is a future surface (P2);
today, one row per org per provider is the rule, and that propagates
to one sidecar per integration row.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class WhatsAppAccountConfig(Base, TenantScoped):
    """Per-(org, integration) WhatsApp Business Account config.

    Survives `disconnect` so a reconnect can pre-fill the phone_id /
    waba_id from history. The plaintext bearer token does NOT survive —
    it lives only inside the parent `Integration.access_token_enc`,
    which the parent's `disconnect` nulls."""

    __tablename__ = "whatsapp_account_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_id: Mapped[str] = mapped_column(Text, nullable=False)
    waba_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    verified_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fernet ciphertext — same key as parent integration's access_token_enc.
    app_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    verify_token: Mapped[str] = mapped_column(Text, nullable=False)
    api_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'v18.0'")
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


__all__ = ["WhatsAppAccountConfig"]
