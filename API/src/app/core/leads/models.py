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
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
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
    # whatsapp-platform-upgrade Step 25 — Flows auto-action for the
    # `lead_capture` category. Migration 0113 added the matching
    # PG enum value via `ALTER TYPE lead_source ADD VALUE`.
    whatsapp_flow = "whatsapp_flow"
    # W6 — walk-in → lead conversion. Migration 0165 adds the PG
    # enum value. Distinguishes hand-typed leads from converted-in-
    # store walk-ins so attribution reports read cleanly.
    walk_in = "walk_in"


lead_source_enum = ENUM(
    LeadSource,
    name="lead_source",
    values_callable=lambda obj: [m.value for m in obj],
)


class Lead(Base, TenantScoped):
    __tablename__ = "tbl_leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # W6 — reverse-link from Lead → originating walk-in (nullable;
    # migration 0161). Populated by ``convert_walk_in_to_lead`` so a
    # lead detail can render "originated from walk-in on X" and
    # analytics can attribute won revenue back to walk-in cohorts.
    # ON DELETE SET NULL — deleting a walk-in preserves the lead but
    # loses the attribution linkage.
    source_walk_in_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_walk_ins.id", ondelete="SET NULL"),
        nullable=True,
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
    # ISO-4217 3-letter currency code (added migration 0160). Nullable
    # — renderers fall back to the org's ``currency`` when unset.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Won-capture fields (migration 0160). Populated by the move-stage
    # service when the destination stage has ``is_won=true``. Symmetric
    # to the lost_reason / lost_reason_other pair below.
    won_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    won_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Lifecycle stamps (migration 0160). Auto-set by the move-stage
    # service on first entry into an is_won / is_lost stage. Feed the
    # funnel time-in-stage report (P.24 workflows analytics + future
    # leads-level dashboards).
    won_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lost_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Operator-defined rule engine output, clamped to [0, 100]. Recomputed
    # by `leads.scoring.recompute_lead` after every create/update that
    # touches a rule-relevant field, and by the hourly Celery sweep when
    # rules themselves change. Indexed `(org_id, lead_score DESC)` in
    # migration 0070 for "hot leads first" sorting.
    lead_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
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
    lost_reason_other: Mapped[str | None] = mapped_column(String(255), nullable=True)
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


class LeadScoringRule(Base, TenantScoped):
    """One operator-defined rule contributing to ``Lead.lead_score``.

    ``condition`` is a Filter-DSL fragment (see
    ``src.app.core.leads.filter_dsl``) evaluated in-memory per lead
    by the scoring engine. Only lead-direct fields are allowed in the
    condition — rules can't reference contact-joined fields because the
    engine doesn't join. ``validate_scorable`` enforces this at the
    rule-create/update API edge.

    ``points`` is bounded to ``[-100, 100]`` (negative points let an
    operator deduct for, e.g., "no_response" status). The aggregate
    score is clamped to ``[0, 100]`` after summing matching rules.
    """

    __tablename__ = "tbl_lead_scoring_rules"
    __table_args__ = (
        CheckConstraint(
            "points BETWEEN -100 AND 100",
            name="ck_lead_scoring_rules_points_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
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
