"""ORM model for `meta_page_tokens` — the per-(integration, page)
Page-token cache populated by Step-4's `subscribe_page` and read by
Step-5's webhook worker.

`page_token_enc` is Fernet ciphertext (Step 1's `crypto`). Plaintext
Page tokens live only inside the request that's about to call the
Graph API, never on the audit/log/response surface.

Not in `core/integrations/models.py` (which holds `Integration`,
`IntegrationSubscription`, `IntegrationDLQ`) because this table is
Meta-specific — a future TikTok integration won't have an equivalent
of Page tokens. Keeping the model next to the Meta code preserves the
rule that the parent `models.py` stays provider-agnostic.
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


class MetaPageToken(Base, TenantScoped):
    """One row per (integration_id, page_id). UNIQUE constraint enforces
    one row per pair; re-subscribing a Page replaces the cached token."""

    __tablename__ = "tbl_meta_page_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[str] = mapped_column(Text, nullable=False)
    page_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fernet ciphertext. Decrypt only when about to call the Graph API.
    page_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


__all__ = ["MetaPageToken"]
