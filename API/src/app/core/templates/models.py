"""Templates module — SQLAlchemy 2.x async models.

Four tables form the central template library. Each is tenant-scoped
via :class:`TenantScoped` (provides ``org_id`` + auto-injects WHERE
``org_id`` filters on every SELECT); each carries a Postgres RLS
policy installed in the matching Alembic migration so the database
itself blocks cross-tenant reads even when an SQL caller forgets to
filter.

The ``channel`` column reuses the existing ``conversation_channel``
PG enum (declared in :mod:`core.conversations.models`); the new
enums ``template_internal_status`` and ``template_external_status``
are created by migration ``0117_templates_schema``.

``tbl_message_templates`` carries every channel-agnostic field;
channel-specific extras (Meta-specific WA header types, future
SMS-DLT entity IDs) live on their own extension tables linked via
``external_provider_id`` text. The parent's ``current_version`` is a
denormalised pointer at the active row in
``tbl_message_template_versions`` — it lets the dispatcher / preview
path read the live body in one query without scanning versions.

``tbl_message_template_reviews`` and ``tbl_message_template_test_sends``
are append-only audit tables. No service writes to them in Step 1;
Steps 4 + 5 wire them.
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


class TemplateInternalStatus(str, enum.Enum):
    """Org-internal review workflow state. Step 4 enforces transitions."""

    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    published = "published"
    archived = "archived"


class TemplateExternalStatus(str, enum.Enum):
    """External provider's verdict for templates that need approval.

    ``n_a``    — channel doesn't require external approval (email,
                 FB Messenger, IG Direct, push). The default.
    ``pending`` — submitted, waiting on the provider.
    ``approved`` — provider approved; ready to send.
    ``rejected`` — provider rejected; ``rejection_reason`` carries the
                   message on the extension table.
    ``paused``   — provider paused due to high failure / spam signals
                   (Meta does this proactively).
    """

    n_a = "n_a"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    paused = "paused"


class TemplateCategory(str, enum.Enum):
    """Send-classification used by the future Send Guard (Step 13 of
    ``tasks/automation-engine/``). Marketing honours DPDP suppression
    + quiet hours + frequency cap; transactional bypasses all three
    (legitimate-interest basis under DPDP); service is the middle
    band — same constraints as marketing but never opt-out-blockable."""

    marketing = "marketing"
    transactional = "transactional"
    service = "service"


class TemplateReviewAction(str, enum.Enum):
    """Action recorded on each review-trail row. Workflow logic (Step 4)
    decides which actions are legal from which state; this enum just
    catalogs the universe."""

    submit = "submit"
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"
    publish = "publish"
    archive = "archive"
    # Step 14 — non-operator action emitted by the manual `/sync-external`
    # endpoint AND the hourly Celery sync. Reviewer is null for
    # automated syncs and the legacy operator id for manual ones; the
    # ``note`` carries the resolved Meta status / rejection_reason.
    external_sync = "external_sync"


template_internal_status_enum = ENUM(
    TemplateInternalStatus,
    name="template_internal_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)

template_external_status_enum = ENUM(
    TemplateExternalStatus,
    name="template_external_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)

template_category_enum = ENUM(
    TemplateCategory,
    name="template_category",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)

template_review_action_enum = ENUM(
    TemplateReviewAction,
    name="template_review_action",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class MessageTemplate(Base, TenantScoped):
    """One reusable message template per row; channel-agnostic.

    The unique constraint is enforced via a functional unique index
    (``org_id, lower(name), channel``) declared in the migration —
    SQLAlchemy ``UniqueConstraint`` can't carry the ``lower()``
    expression, so it's intentionally absent from ``__table_args__``.
    """

    __tablename__ = "tbl_message_templates"
    __table_args__ = (
        Index(
            "ix_message_templates_org_channel_internal_status",
            "org_id",
            "channel",
            "internal_status",
        ),
        Index(
            "ix_message_templates_org_external_status",
            "org_id",
            "external_status",
            postgresql_where=sql_text("external_status <> 'n_a'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    channel: Mapped[ConversationChannel] = mapped_column(conversation_channel_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[TemplateCategory] = mapped_column(
        template_category_enum,
        nullable=False,
        server_default=sql_text("'marketing'"),
    )
    language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=sql_text("'en'"),
    )
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Campaigns v1 Step 04 — HTML body for Email templates. Sanitised
    # by :mod:`core.templates.sanitizer` on every write. NULL for
    # non-Email channels; kept nullable on Email too so a text-only
    # template still round-trips through the schema layer.
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When true, dispatch (Step 05) auto-derives ``body_text`` from
    # ``body_html`` for the Gmail multipart fallback when the user
    # left ``body_text`` empty. When false, the operator explicitly
    # authored both halves and dispatch uses them verbatim.
    body_text_fallback_auto: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("true"),
    )
    # Email-only — null for every other channel. Push title repurposes
    # this column with a UI label of "Title" (decided in Step 13). The
    # 998-char ceiling matches RFC 5322 subject-line max; push truncates
    # to its own 50-char limit in the editor layer.
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    preview_text: Mapped[str | None] = mapped_column(String(190), nullable=True)
    # Set of ``{{var}}`` references the body uses, parsed by the
    # service layer on create/update (Step 2). Stored as a list of
    # strings, e.g. ``["contact.first_name", "org.name"]``.
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    internal_status: Mapped[TemplateInternalStatus] = mapped_column(
        template_internal_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    external_status: Mapped[TemplateExternalStatus] = mapped_column(
        template_external_status_enum,
        nullable=False,
        server_default=sql_text("'n_a'"),
    )
    # Meta template id / future DLT template id / future provider ids.
    # Kept as free text because each provider's id shape differs.
    external_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("1")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Owner / Admin (or any role with ``templates.activate``) can flip
    # a template inactive to keep the row in the library but block every
    # send path from using it. Campaigns, workflows, automations, and
    # the conversations composer all filter this out server-side + hide
    # inactive rows in their pickers. Default true so existing rows +
    # every newly-created template are usable out of the box.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
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
    )


class MessageTemplateVersion(Base, TenantScoped):
    """Immutable per-edit snapshot. Step 2's service writes a new row
    on every PATCH; the parent's ``current_version`` is bumped to
    match the new row's ``version`` int."""

    __tablename__ = "tbl_message_template_versions"
    __table_args__ = (
        Index(
            "ix_message_template_versions_template_version",
            "template_id",
            "version",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Campaigns v1 Step 04 — HTML body snapshot per version (mirrors
    # the parent's ``body_html``). NULL for non-Email + for legacy
    # rows created before the migration.
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class MessageTemplateReview(Base, TenantScoped):
    """Append-only review trail. One row per workflow transition
    (Step 4 wires the writes). Used by Step 8's review modal +
    versions drawer to show ``who approved`` / ``why rejected``."""

    __tablename__ = "tbl_message_template_reviews"
    __table_args__ = (
        Index(
            "ix_message_template_reviews_template_created_at",
            "template_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[TemplateReviewAction] = mapped_column(
        template_review_action_enum, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class MessageTemplateTestSend(Base, TenantScoped):
    """Append-only audit of every operator-initiated test send. Step 5's
    test-send service writes rows; Step 8's modal triggers the
    sends. ``channel_message_id`` comes back from the adapter when
    the send succeeds (NULL for failures so the row still records
    the attempt)."""

    __tablename__ = "tbl_message_template_test_sends"
    __table_args__ = (
        Index(
            "ix_message_template_test_sends_template_sent_at",
            "template_id",
            "sent_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[ConversationChannel] = mapped_column(conversation_channel_enum, nullable=False)
    sent_to: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


# tasks/template-library Step 12 — re-export the SMS-DLT extension
# model so the `*.models` pin-test sweep sees it + so
# `Base.metadata` registers the table for test-DB `create_all`. The
# model body lives in `sms_extension.py` alongside its service
# helpers; this is a registration-only import.
from src.app.core.templates.sms_extension import SMSDLTTemplate  # noqa: E402, F401
