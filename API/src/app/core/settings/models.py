"""`OrgSettings` — one row per organisation, holding the editable
preferences the Settings page exposes.

Single-row-per-org enforced by `(org_id) PRIMARY KEY` (composed with
the TenantScoped mixin, which already requires `org_id` on every
table). The pack installer (4.2) writes the furniture-specific
defaults; this core model holds only generic-CRM keys (rule 7 —
no furniture-specific defaults in core).

Tenant-scoped, RLS on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class OrgSettings(Base, TenantScoped):
    __tablename__ = "tbl_org_settings"
    __table_args__ = (UniqueConstraint("org_id", name="uq_org_settings_org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )

    # --- store profile ---
    store_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- locale / fiscal ---
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=sql_text("'INR'")
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=sql_text("18.00")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=sql_text("'Asia/Kolkata'")
    )
    locale: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=sql_text("'en-IN'")
    )

    # --- AI ---
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    ai_personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- reviews automation ---
    reviews_auto_request_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    reviews_auto_request_delay_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("24")
    )

    # --- template-library review workflow (tasks/template-library Step 4) ---
    # When True the workflow refuses ``draft → published`` shortcuts
    # — every template must go through ``in_review → approved`` before
    # publish. When False the operator can publish directly from draft.
    template_review_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    # When False the reviewer must be a different user from the
    # template's author. When True an Owner / Admin can approve their
    # own drafts (useful for solo / small-team orgs).
    template_review_self_approve_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )

    # --- lead routing (Step 6) ---
    # Per-org routing config — JSONB so the schema is forward-compatible
    # with strategies we haven't built yet. v1 honours `{"strategy":
    # "round_robin"}` only; future keys (`sticky_by_source`,
    # `by_geography`, weighted distribution) slot in without a
    # migration. The Settings endpoint validates the shape.
    lead_routing_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text('\'{"strategy":"round_robin"}\'::jsonb'),
    )

    # --- compliance gates (tasks/workflows Step 12) ---
    # DPDP / India-default quiet hours + frequency cap settings for
    # marketing-category sends. Transactional sends (quote / invoice
    # receipts) bypass per the documented legitimate-interest
    # carve-out. The Step-12 ``core/workflows/compliance.py`` helper
    # reads these on every Send action's pre-flight.
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    quiet_hours_start: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=sql_text("'21:00:00'")
    )
    quiet_hours_end: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=sql_text("'09:00:00'")
    )
    quiet_hours_timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'Asia/Kolkata'")
    )
    frequency_cap_marketing_per_week: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("5")
    )
    frequency_cap_marketing_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("2")
    )
    transactional_bypass_quiet_hours: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    transactional_bypass_frequency_cap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    unsubscribe_link_required_in_marketing_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )

    # --- workflow routing state (tasks/workflows Step 9) ---
    # Per-pool round-robin pointer state. Keyed by ``pool_spec``
    # string (e.g. ``"role:Sales"``) → ``{"last_picked_user_id":
    # "<uuid>", "last_picked_at": "<iso>"}``. Mutated under a
    # ``SELECT ... FOR UPDATE`` row lock on this row so concurrent
    # workflow firings can't double-assign or skip a user. Kept
    # tiny — one entry per (org, pool_spec) the operator's
    # workflows reference.
    routing_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )
