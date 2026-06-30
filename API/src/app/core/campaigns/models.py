"""Campaigns engine models.

Two tables:

- `Campaign` — one row per outbound marketing/transactional campaign.
  `channel` reuses the same `ConversationChannel` enum from 3.8 so the
  campaigns engine sends through the same adapter registry as
  Conversations (no per-channel logic anywhere in this module).
  `audience_filter` is JSONB shaped like a `/contacts` query so the
  same query builder resolves it (`q`, `source`, `tag`).
- `CampaignMessage` — one row per (campaign × contact). Records the
  channel-side `channel_message_id` (for stats joins later) plus a
  delivery-status enum the channel adapter / webhook updates.

`CampaignStats` is computed on-the-fly from `CampaignMessage` (no
denormalised view at this stage — we'll add a materialised view if /
when the count GROUP BYs get expensive). The `stats` endpoint groups
by `status` and returns counts that the UI charts.

Tenant-scoped, RLS on. Migration 0021 adds hot-path indexes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.conversations.models import (
    ConversationChannel,
    conversation_channel_enum,
)
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    done = "done"
    failed = "failed"


class CampaignMessageStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


campaign_status_enum = ENUM(
    CampaignStatus,
    name="campaign_status",
    values_callable=lambda obj: [m.value for m in obj],
)

campaign_message_status_enum = ENUM(
    CampaignMessageStatus,
    name="campaign_message_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class Campaign(Base, TenantScoped):
    __tablename__ = "tbl_campaigns"
    __table_args__ = (
        Index("ix_campaigns_org_status", "org_id", "status"),
        Index("ix_campaigns_org_schedule_at", "org_id", "schedule_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[ConversationChannel] = mapped_column(conversation_channel_enum, nullable=False)
    audience_filter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    template: Mapped[str | None] = mapped_column(
        # Free-text body for non-template campaigns (any channel) +
        # legacy WhatsApp text campaigns. For WA campaigns that use an
        # approved Meta template, `template_id` is set instead and
        # this column is NULL. Schema-level validation in
        # `CampaignCreate` enforces "exactly one of template or
        # template_id".
        String(4096),
        nullable=True,
    )
    # WA template campaigns reference an approved Meta template by id.
    # ON DELETE SET NULL preserves the campaign row if Meta deletes
    # the template (Step 3.5.4 hard-delete on sync); the dispatch path
    # will then fail with a clear "template no longer exists" error.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Operator's variable bindings — shape:
    #   {"1": {"kind":"static","value":"30%"},
    #    "2": {"kind":"field","value":"full_name"}}
    # Step 3.5.6's dispatch resolves `kind=field` against each contact
    # at send time. `kind=static` passes through verbatim.
    template_variables: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    schedule_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # whatsapp-platform-upgrade Step 27a — multi-number per org.
    # When set, the dispatcher resolves this specific WhatsApp
    # config instead of the org's default phone. NULL preserves
    # the original behaviour for every existing campaign row.
    send_from_phone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # whatsapp-platform-upgrade Step 29 — A/B testing.
    # ``is_ab_test`` is the master gate; when False every other
    # A/B column is ignored. When True the dispatcher assigns each
    # recipient to A or B per ``split_ratio``, the Celery decider
    # runs after ``winner_holdback_hours``, and remaining unsent
    # recipients receive the winning template.
    is_ab_test: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    variant_a_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    variant_b_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    split_ratio: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("50"),
    )
    winner_metric: Mapped[str | None] = mapped_column(
        ENUM(
            "reply_rate",
            "read_rate",
            "click_rate",
            name="campaign_winner_metric",
            create_type=False,
        ),
        nullable=True,
    )
    winner_holdback_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("24"),
    )
    winner_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    winning_variant: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        campaign_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class CampaignMessage(Base, TenantScoped):
    __tablename__ = "tbl_campaign_messages"
    __table_args__ = (
        Index(
            "ix_campaign_messages_campaign_status",
            "campaign_id",
            "status",
        ),
        Index(
            "ix_campaign_messages_campaign_contact",
            "campaign_id",
            "contact_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CampaignMessageStatus] = mapped_column(
        campaign_message_status_enum,
        nullable=False,
        server_default=sql_text("'queued'"),
    )
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Meta status webhook timestamps (Step 3.5.12). NULL until the
    # corresponding `statuses[]` event arrives from Meta. The
    # Step 3.5.13 UI uses these to render the WhatsApp tick state
    # (✓ sent / ✓✓ delivered / ✓✓ blue read) per message.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # whatsapp-platform-upgrade Step 29 — A/B test variant marker.
    # ``'A'`` / ``'B'`` for recipients dispatched during the A/B
    # hold-out window; ``NULL`` for non-A/B campaigns + recipients
    # sent after the winner was decided (those receive the winning
    # template directly without a variant tag).
    variant: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
