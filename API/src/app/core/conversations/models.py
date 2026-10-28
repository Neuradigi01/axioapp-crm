"""Conversations engine models — channel-agnostic.

Two tables:

- `Conversation` — one row per (channel, external_id) pair. Holds the
  participant identity at the channel layer (e.g. WhatsApp phone) and
  the CRM-side denormalised counters that the inbox needs to render a
  list fast: `last_message_at` (for sort), `unread_count` (for the
  badge), `status` (open/snoozed/closed), `ai_handling` (boolean for
  the AI auto-reply toggle from Phase 5.7).
- `Message` — one row per inbound or outbound message. `direction` is
  `in` or `out`; `channel_message_id` is the channel-side identifier
  so we can dedupe webhook replays.

The engine is intentionally agnostic of *which* channel — adapters
(WhatsApp etc.) live under `adapters/` and the registry resolves them
at runtime. Migration 0018 enforces RLS + the hot-path indexes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class ConversationChannel(str, enum.Enum):
    whatsapp = "whatsapp"
    instagram = "instagram"
    facebook = "facebook"
    web = "web"
    sms = "sms"
    email = "email"
    # tasks/template-library Step 13 — push notifications as a
    # first-class template channel. No transport behind it; the
    # registered adapter raises ``PushNotConfigured`` on send until a
    # provider (Firebase / OneSignal / APNS) is wired.
    push = "push"


class ConversationStatus(str, enum.Enum):
    open = "open"
    snoozed = "snoozed"
    closed = "closed"


class MessageDirection(str, enum.Enum):
    in_ = "in"
    out = "out"


conversation_channel_enum = ENUM(
    ConversationChannel,
    name="conversation_channel",
    values_callable=lambda obj: [m.value for m in obj],
)

conversation_status_enum = ENUM(
    ConversationStatus,
    name="conversation_status",
    values_callable=lambda obj: [m.value for m in obj],
)

message_direction_enum = ENUM(
    MessageDirection,
    name="message_direction",
    values_callable=lambda obj: [m.value for m in obj],
)


class Conversation(Base, TenantScoped):
    __tablename__ = "tbl_conversations"
    __table_args__ = (
        Index(
            "ix_conversations_org_last_message",
            "org_id",
            "last_message_at",
        ),
        Index(
            "ix_conversations_channel_external_id",
            "channel",
            "external_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    channel: Mapped[ConversationChannel] = mapped_column(conversation_channel_enum, nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # whatsapp-platform-upgrade Step 27a — the Meta phone_number_id
    # the inbound message arrived on (multi-number per org). NULL on
    # conversations created before 0115 or via the manual outbound
    # path. The chat-thread composer reads this to default Send-From
    # back to the same number the customer reached us on.
    received_via_phone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        conversation_status_enum,
        nullable=False,
        server_default=sql_text("'open'"),
    )
    ai_handling: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # whatsapp-platform-upgrade Step 15 — timestamp of the most recent
    # *customer-driven* message in this conversation. Used to compute
    # the WhatsApp 24-hour session window. NULL when the customer has
    # never sent a message (session-helper treats NULL as out-of-session).
    # Updated atomically with every inbound message insert in
    # `service.receive_webhook`.
    last_customer_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    # whatsapp-platform-upgrade Step 24 — click-to-WhatsApp ad
    # attribution. Single-touch: set on the first inbound that
    # carries a Meta `referral` block; never overwritten on later
    # messages. NULL on every pre-existing conversation (treated as
    # organic). The `acquisition_referral_payload` JSONB preserves
    # the raw Meta object so future Meta-side fields stay queryable
    # without a schema migration.
    acquisition_source: Mapped[str | None] = mapped_column(
        ENUM(
            "organic",
            "ad",
            "qr",
            "wa_me",
            "form",
            name="conversation_acquisition_source",
            create_type=False,
        ),
        nullable=True,
    )
    acquisition_campaign_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquisition_ad_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquisition_landing_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    acquisition_referral_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class Message(Base, TenantScoped):
    __tablename__ = "tbl_messages"
    __table_args__ = (
        Index(
            "ix_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction: Mapped[MessageDirection] = mapped_column(message_direction_enum, nullable=False)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'[]'::jsonb"),
    )
    channel_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    # whatsapp-platform-upgrade Step 6: outbound Meta interactive
    # envelope (reply buttons / CTA / list). NULL on text + media +
    # template rows. The thread bubble renders this so button labels
    # stay visible even months after send; replay audits also read
    # from here.
    interactive_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # whatsapp-platform-upgrade Step 7: reply-to / reactions.
    # `reply_to_message_id` is a self-FK to the message being quoted —
    # `ON DELETE SET NULL` so a deleted original leaves the reply intact
    # with a "deleted" placeholder. `reactions` is an append/replace
    # list of `{user, emoji, ts}` dicts — one row per reactor (Meta caps
    # at one reaction per user per message). Inbound reactions write to
    # the *target* message's column, not the reaction event's own row.
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    reactions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'[]'::jsonb"),
    )
    # whatsapp-platform-upgrade Step 13 — internal notes + @mentions.
    # `is_internal=true` rows are operator-only — the engine refuses
    # to dispatch them via any channel adapter, and they're styled
    # yellow in the thread. `mentioned_user_ids` is the list of staff
    # the note's author tagged with `@name`; the notes service writes
    # one notification per id on insert.
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    mentioned_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=sql_text("'{}'::uuid[]"),
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )

    @property
    def is_ai(self) -> bool:
        """True when this outbound message was authored by the AI
        agent (whatsapp-platform-upgrade Step 19). Reads
        ``payload['author']`` so the wire schema can expose a simple
        bool without leaking the full payload dict. Frontend bubble
        renders the 🤖 AI badge on this."""
        payload = self.payload or {}
        if not isinstance(payload, dict):
            return False
        return payload.get("author") == "ai"


class ConversationTag(Base, TenantScoped):
    """Operator-defined label for conversations
    (whatsapp-platform-upgrade Step 14).

    Org-scoped, case-insensitively unique per-org by name. `color` is
    a fixed-palette key the frontend maps to a Tailwind class set —
    keeps the column small + the choices accessible."""

    __tablename__ = "tbl_conversation_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    color: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        server_default=sql_text("'zinc'"),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class ConversationTagAssignment(Base, TenantScoped):
    """Many-to-many between conversations and tags. CASCADE on both
    legs so deleting a tag or a conversation cleans up the bridge
    rows automatically."""

    __tablename__ = "tbl_conversation_tag_assignments"
    __table_args__ = (UniqueConstraint("conversation_id", "tag_id", name="uq_conv_tag_assignment"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversation_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    tagged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
