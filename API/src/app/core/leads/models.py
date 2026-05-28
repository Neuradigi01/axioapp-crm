"""`Lead` model — a prospective sale tracked through the `leads` pipeline.

Each lead references one `contacts` row (the person being sold to) and
sits in one stage of the `leads` pipeline at any time. `pipeline_stage`
stores the stage's stable `key` (text), not its UUID, because stage
UUIDs change on re-seed but keys do not — matches the convention
established by the pipelines engine in Step 2.9.

`status` (active/won/lost) is auto-synced with the destination stage's
`is_won`/`is_lost` flags every time `POST /leads/{id}/move-stage` runs.
The two fields can drift if rows are mutated by raw SQL outside the
service, but never through the HTTP surface.

Tenant-scoped (RLS on, ORM filter applied). Indexed for the hot path:
`(org_id, pipeline_stage)` for the kanban "show this column" reads;
`assigned_to_id` for "my leads".
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class LeadStatus(str, enum.Enum):
    active = "active"
    won = "won"
    lost = "lost"


lead_status_enum = ENUM(
    LeadStatus,
    name="lead_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class LeadSource(str, enum.Enum):
    """Provenance of a lead row. One of five fixed ingestion channels.

    Stamped at create time and immutable afterwards (no update endpoint
    exposes it). New channels require both an enum value here AND a
    matching value in the PG `lead_source_enum` type via a migration.
    """

    manual = "manual"
    bulk_import = "bulk_import"
    widget = "widget"
    google_ads = "google_ads"
    meta_ads = "meta_ads"


lead_source_enum = ENUM(
    LeadSource,
    name="lead_source",
    values_callable=lambda obj: [m.value for m in obj],
)


class Lead(Base, TenantScoped):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pipeline_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        lead_status_enum,
        nullable=False,
        server_default=text("'active'"),
    )
    source: Mapped[LeadSource] = mapped_column(
        lead_source_enum,
        nullable=False,
        server_default=text("'manual'"),
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook. Mirrors `contacts.last_activity_at`.
    # Source of truth lives in the `activities` table.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Required when the lead's pipeline-stage flips to `is_lost=true`
    # (enforced in `move_stage_for_lead`). Picklist values are pinned
    # in the DB via the `ck_leads_lost_reason_picklist` CHECK
    # constraint added in migration 0054.
    lost_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lost_reason_other: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Channel-supplied provenance (widget UTM, ad webhook ids, etc.).
    # Nullable — manual + bulk-import leads typically have no attribution
    # to capture; widget + ad-integration channels populate it.
    attribution: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
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
