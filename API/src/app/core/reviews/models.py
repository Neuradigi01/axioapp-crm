"""Reviews model.

One table — `Review` — generic across review sources. `source` is a
free-form short string (`"google"`, `"facebook"`, `"internal"`, …) so
new sources (Justdial, Sulekha, the in-store kiosk) don't need a
migration. The furniture pack defaults this to `"google"` in 4.x; core
stays source-agnostic (rule 3 spirit — engine generic, defaults live
in the pack).

`status` IS enum-restricted (pending_reply / replied / escalated)
because the workflow UI relies on a bounded set.

Tenant-scoped, RLS on. Migration 0020 adds hot-path indexes:
`(org_id, rating)` for distribution group-bys and `(org_id, source)`
for per-source filtering.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class ReviewStatus(str, enum.Enum):
    pending_reply = "pending_reply"
    replied = "replied"
    escalated = "escalated"


review_status_enum = ENUM(
    ReviewStatus,
    name="review_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class Review(Base, TenantScoped):
    __tablename__ = "tbl_reviews"
    __table_args__ = (
        Index("ix_reviews_org_rating", "org_id", "rating"),
        Index("ix_reviews_org_source", "org_id", "source"),
        Index("ix_reviews_org_created_at", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Channel-side review id (Google review id, FB post id, etc.).
    # Optional — internal reviews entered by an agent don't have one.
    source_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replied_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        review_status_enum,
        nullable=False,
        server_default=sql_text("'pending_reply'"),
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default=sql_text("ARRAY[]::varchar[]"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
