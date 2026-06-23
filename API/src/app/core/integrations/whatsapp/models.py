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

import enum
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class WhatsAppTemplateSubmissionStatus(str, enum.Enum):
    """Operator-side lifecycle for a WhatsApp template
    (whatsapp-platform-upgrade Step 8).

    Distinct from the legacy ``status`` column, which carries Meta's
    raw status text verbatim. The two coexist: ``status`` reflects
    what Meta last told us; ``submission_status`` reflects what the
    operator did in the CRM. They diverge during the brief window
    between a Submit click and the next ``message_template_status_update``
    webhook (status='PENDING' / submission_status='pending_review')."""

    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    paused = "paused"
    disabled = "disabled"


whatsapp_template_submission_status_enum = ENUM(
    WhatsAppTemplateSubmissionStatus,
    name="whatsapp_template_submission_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


_VARIABLE_RE = re.compile(r"\{\{(\d+)\}\}")


class WhatsAppAccountConfig(Base, TenantScoped):
    """Per-(org, integration) WhatsApp Business Account config.

    Survives `disconnect` so a reconnect can pre-fill the phone_id /
    waba_id from history. The plaintext bearer token does NOT survive —
    it lives only inside the parent `Integration.access_token_enc`,
    which the parent's `disconnect` nulls."""

    __tablename__ = "tbl_whatsapp_account_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_id: Mapped[str] = mapped_column(Text, nullable=False)
    waba_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    verified_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fernet ciphertext — same key as parent integration's access_token_enc.
    # Nullable since whatsapp-platform-upgrade Step 2: Embedded Signup
    # orgs share one platform-level secret via env (`WHATSAPP_APP_SECRET`)
    # and don't need a per-org row here. Legacy manually-connected orgs
    # keep their per-org ciphertext as the signature-verifier fallback.
    app_secret_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verify_token: Mapped[str] = mapped_column(Text, nullable=False)
    api_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'v18.0'")
    )
    # Step 3.5.15 — per-org outbound rate cap (msg/sec). Operator-set
    # in Settings → Integrations → WhatsApp → Advanced. Free-tier Meta
    # WABAs are ~50/sec; business-verified can go up to 1000.
    rate_limit_per_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("50")
    )
    # Step 3.5.16 — cache of Meta's `messaging_limit_tier` (TIER_50,
    # TIER_250, TIER_1K, TIER_10K, TIER_100K, TIER_UNLIMITED). NULL
    # until the first capacity lookup populates it. Refreshed when
    # `tier_synced_at` is older than 1 hour to keep the Graph API call
    # rate well under Meta's per-token throttle.
    messaging_limit_tier: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    tier_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # whatsapp-platform-upgrade Step 12 — phone health snapshot.
    # Cached per hourly refresh by `health_service.refresh_from_meta`.
    # `health_synced_at` lets the UI render staleness; the event log
    # in `tbl_whatsapp_phone_health_events` carries the timeline of
    # changes.
    quality_rating: Mapped[Optional[str]] = mapped_column(
        String(length=16), nullable=True
    )
    name_status: Mapped[Optional[str]] = mapped_column(
        String(length=32), nullable=True
    )
    throughput: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    restrictions: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    health_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # whatsapp-platform-upgrade Step 11 — Meta Business profile editor.
    # Mirrors the `whatsapp_business_profile` Graph endpoint shape;
    # populated by `business_profile.refresh_from_meta` on first open
    # and on the operator-side Refresh button.
    profile_about: Mapped[Optional[str]] = mapped_column(
        String(length=139), nullable=True
    )
    profile_description: Mapped[Optional[str]] = mapped_column(
        String(length=512), nullable=True
    )
    profile_address: Mapped[Optional[str]] = mapped_column(
        String(length=256), nullable=True
    )
    profile_email: Mapped[Optional[str]] = mapped_column(
        String(length=128), nullable=True
    )
    profile_websites: Mapped[Optional[list[str]]] = mapped_column(
        JSONB, nullable=True
    )
    profile_vertical: Mapped[Optional[str]] = mapped_column(
        String(length=64), nullable=True
    )
    profile_picture_url: Mapped[Optional[str]] = mapped_column(
        String(length=512), nullable=True
    )
    profile_last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Day-of-week schedule (storage only — Step 16 reads to decide
    # whether the away message fires). Shape:
    #   [{day: 0..6, intervals: [{open: "10:00", close: "19:00"}, …]}]
    # Day 0 = Monday. Closed days omit intervals.
    business_hours: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    # Free-text storage for the Step-16 automation. Variable
    # substitution ({{contact.first_name}} etc.) happens at send time;
    # Step 11 only persists the template text.
    greeting_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    away_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # whatsapp-platform-upgrade Step 16 — auto-reply pipeline toggles
    # + out-of-session template fallbacks. The greeting / away text
    # above is used in-session (free-text reply); when the contact
    # is outside their 24-hour session window, the linked approved
    # template fires instead.
    greeting_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    away_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    greeting_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_whatsapp_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    away_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_whatsapp_templates.id", ondelete="SET NULL"),
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


class WhatsAppTemplate(Base, TenantScoped):
    """Per-(org, integration) cache of one Meta-approved WhatsApp
    message template.

    Populated by `templates.sync_templates`; read by the campaign
    template picker (Step 3.5.5) and by `dispatch_chunk`'s template
    branch (Step 3.5.6).

    `variable_count` is precomputed at sync time from the `{{n}}`
    placeholder count in `body` so the picker doesn't re-parse the
    body on every render. `meta_template_id` is kept for forensic
    traceability; idempotent upsert is keyed on
    `(integration_id, name, language)` because Meta's id can change
    when a template is edited."""

    __tablename__ = "tbl_whatsapp_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    header_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    header_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    footer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variable_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    meta_template_id: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # whatsapp-platform-upgrade Step 8 — structured Meta component
    # payload. NULL for legacy sync rows (the next sync round repops);
    # populated on every new draft so we can resubmit verbatim. Each
    # element is a `{type, format?, text?, buttons?[]}` dict matching
    # Meta's `/{waba_id}/message_templates` POST shape.
    body_components: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    submission_status: Mapped[WhatsAppTemplateSubmissionStatus] = (
        mapped_column(
            whatsapp_template_submission_status_enum,
            nullable=False,
            server_default=text("'draft'"),
        )
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    submitted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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

    @property
    def variables(self) -> list[int]:
        """Sorted unique placeholder numbers found in the body — the
        picker (Step 3.5.5) uses this to render one input per variable."""
        return sorted({int(m) for m in _VARIABLE_RE.findall(self.body)})


class WhatsAppPhoneHealthEventType(str, enum.Enum):
    """Phone-health event-log discriminator
    (whatsapp-platform-upgrade Step 12)."""

    quality_change = "quality_change"
    tier_change = "tier_change"
    name_status_change = "name_status_change"
    restriction_added = "restriction_added"
    restriction_lifted = "restriction_lifted"


whatsapp_phone_health_event_type_enum = ENUM(
    WhatsAppPhoneHealthEventType,
    name="whatsapp_phone_health_event_type",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WhatsAppPhoneHealthEvent(Base, TenantScoped):
    """Append-only audit log of phone-health changes.

    Written by the hourly refresh task and the
    ``phone_number_quality_update`` webhook handler whenever a field
    moves. `occurred_at` is the wall-clock from Meta's payload (when
    available) so timeline rendering survives out-of-order webhook
    delivery. `recorded_at` is the row insert time."""

    __tablename__ = "tbl_whatsapp_phone_health_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    phone_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
    event_type: Mapped[WhatsAppPhoneHealthEventType] = mapped_column(
        whatsapp_phone_health_event_type_enum, nullable=False
    )
    old_value: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    new_value: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class KeywordMatchType(str, enum.Enum):
    """How a rule's keyword list is tested against inbound text
    (whatsapp-platform-upgrade Step 17).

    * ``contains`` — case-insensitive substring; matches if ANY
      keyword is found inside the text.
    * ``exact`` — case-insensitive exact match against the whole
      message body.
    * ``regex`` — Python ``re.search`` with the keyword as a regex.
      Length-capped + try/except-wrapped at evaluation time to
      survive operator typos."""

    contains = "contains"
    exact = "exact"
    regex = "regex"


class KeywordActionType(str, enum.Enum):
    reply_text = "reply_text"
    reply_template = "reply_template"
    tag_conversation = "tag_conversation"
    assign_to_user = "assign_to_user"
    escalate_to_ai = "escalate_to_ai"


whatsapp_keyword_match_type_enum = ENUM(
    KeywordMatchType,
    name="whatsapp_keyword_match_type",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)

whatsapp_keyword_action_type_enum = ENUM(
    KeywordActionType,
    name="whatsapp_keyword_action_type",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WhatsAppKeywordRule(Base, TenantScoped):
    """One operator-defined rule
    (whatsapp-platform-upgrade Step 17).

    Evaluated in `priority` ascending order — lower number = higher
    priority. The first rule that matches an inbound message fires
    its actions and short-circuits the rest of the evaluation loop
    (Step 17 spec; future "continue on match" toggle would live on
    this row)."""

    __tablename__ = "tbl_whatsapp_keyword_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(length=128), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    match_type: Mapped[KeywordMatchType] = mapped_column(
        whatsapp_keyword_match_type_enum,
        nullable=False,
        server_default=text("'contains'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
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


class WhatsAppKeywordAction(Base, TenantScoped):
    """One action attached to a rule. Multiple actions per rule run
    in `position` order — a rule can reply with a template, tag the
    conversation, AND escalate to AI on one match."""

    __tablename__ = "tbl_whatsapp_keyword_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tbl_whatsapp_keyword_rules.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    action_type: Mapped[KeywordActionType] = mapped_column(
        whatsapp_keyword_action_type_enum, nullable=False
    )
    action_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AssignmentStrategy(str, enum.Enum):
    """Auto-assignment strategy
    (whatsapp-platform-upgrade Step 18).

    Each strategy reads a different shape of ``config`` JSONB; the
    engine + schema layer enforce per-strategy config validation."""

    round_robin = "round_robin"
    load_balanced = "load_balanced"
    tag_based = "tag_based"
    team_based = "team_based"


whatsapp_assignment_strategy_enum = ENUM(
    AssignmentStrategy,
    name="whatsapp_assignment_strategy",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WhatsAppAssignmentRule(Base, TenantScoped):
    """One operator-defined assignment rule
    (whatsapp-platform-upgrade Step 18).

    The engine walks active rules in `priority` ascending order on
    every new (still-unassigned) conversation. ``last_assigned_user_id``
    is the round-robin cursor — the engine reads + writes it under
    a ``SELECT FOR UPDATE`` lock so concurrent webhooks don't all
    pick the same user."""

    __tablename__ = "tbl_whatsapp_assignment_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(length=128), nullable=False)
    strategy: Mapped[AssignmentStrategy] = mapped_column(
        whatsapp_assignment_strategy_enum, nullable=False
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    skip_outside_hours: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_assigned_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
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


__all__ = [
    "AssignmentStrategy",
    "KeywordActionType",
    "KeywordMatchType",
    "WhatsAppAccountConfig",
    "WhatsAppAssignmentRule",
    "WhatsAppKeywordAction",
    "WhatsAppKeywordRule",
    "WhatsAppPhoneHealthEvent",
    "WhatsAppPhoneHealthEventType",
    "WhatsAppTemplate",
    "WhatsAppTemplateSubmissionStatus",
]
