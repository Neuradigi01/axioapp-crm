"""Pydantic v2 schemas for the central template library.

Step 1 lands shapes only — no service / router consumes them yet
(Steps 2 + 3 do). The shapes mirror the SQLAlchemy models in
:mod:`core.templates.models` with channel-aware validation:
``subject`` + ``preview_text`` must be ``None`` for non-email
channels, and the email channel must carry a non-empty subject.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.shared.schemas.base import ORMModel

# ---- WhatsApp extension sub-payload ----------------------------------


class WhatsAppTemplateButton(BaseModel):
    """One CTA button on a WA template. Meta caps at 3 per template
    and each type has its own required companion field:

      * ``url`` — ``text`` + ``url``
      * ``phone_number`` — ``text`` + ``phone_number``
      * ``quick_reply`` — ``text`` only
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    type: str = Field(pattern=r"^(url|phone_number|quick_reply)$")
    text: str = Field(min_length=1, max_length=25)
    url: str | None = Field(default=None, max_length=2000)
    phone_number: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _type_companion_required(self) -> WhatsAppTemplateButton:
        if self.type == "url" and not (self.url and self.url.strip()):
            raise ValueError("url is required for a URL button")
        if self.type == "phone_number" and not (
            self.phone_number and self.phone_number.strip()
        ):
            raise ValueError("phone_number is required for a Phone button")
        return self


class WhatsAppExtensionPayload(BaseModel):
    """Optional Meta-specific fields for WhatsApp templates.

    Only meaningful on WA-channel templates; ignored (and rejected via
    the model validator on TemplateCreate) for other channels. Every
    field is optional — a WA template can ship body-only.

    ``category`` uses Meta's taxonomy (Marketing / Utility /
    Authentication) which is DIFFERENT from the central row's
    ``TemplateCategory`` (marketing / transactional / service — the
    send-guard classification). Both live independently; the send
    guard reads the central column, the Submit-to-Meta payload reads
    this one.

    ``header_type`` supports the four Meta formats. When ``text`` is
    picked, ``header_text`` carries the text; the ``image`` /
    ``video`` / ``document`` variants require operators to upload a
    sample via the existing WA templates upload flow.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category: str | None = Field(
        default=None, pattern=r"^(marketing|utility|authentication)$"
    )
    header_type: str | None = Field(
        default=None, pattern=r"^(text|image|video|document)$"
    )
    header_text: str | None = Field(default=None, max_length=60)
    footer_text: str | None = Field(default=None, max_length=60)
    buttons: list[WhatsAppTemplateButton] | None = Field(default=None, max_length=3)


# ---- Request shapes ---------------------------------------------------


class TemplateCreate(BaseModel):
    """Payload for ``POST /api/v1/templates`` (Step 3).

    The variables list is NOT accepted from the client — Step 2's
    service parses ``body_text`` for ``{{var}}`` references and
    populates ``tbl_message_templates.variables`` itself. Clients
    that hand-author a list would otherwise drift from the body.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    channel: ConversationChannel
    category: TemplateCategory = TemplateCategory.marketing
    language: str = Field(default="en", min_length=2, max_length=16)
    # Campaigns v1 Step 04 — Email templates can carry an HTML body
    # instead of / alongside the plain text. Non-Email channels keep
    # body_text as the source of truth (validator enforces below).
    body_text: str | None = Field(default=None, max_length=65535)
    body_html: str | None = Field(default=None, max_length=200_000)
    body_text_fallback_auto: bool = True
    subject: str | None = Field(default=None, max_length=998)
    preview_text: str | None = Field(default=None, max_length=190)
    # Meta-specific extras — only accepted when channel=whatsapp. The
    # service layer upserts a matching WhatsAppTemplate extension row.
    whatsapp: WhatsAppExtensionPayload | None = None

    @model_validator(mode="after")
    def _email_channel_body_and_subject(self) -> TemplateCreate:
        """Channel-branched invariants:

        * Email — at least one of ``body_text`` / ``body_html`` non-empty,
          ``subject`` required, ``preview_text`` allowed.
        * Non-Email — ``body_text`` non-empty required, ``body_html``
          must be null, ``subject`` + ``preview_text`` must be null.

        The service layer sanitises ``body_html`` and, when
        ``body_text_fallback_auto`` is true and ``body_text`` was
        omitted, derives it from the sanitised HTML before persisting.
        """
        has_text = bool(self.body_text and self.body_text.strip())
        has_html = bool(self.body_html and self.body_html.strip())
        if self.channel == ConversationChannel.email:
            if not has_text and not has_html:
                raise ValueError(
                    "email templates require body_text or body_html (or both)"
                )
            if not self.subject or not self.subject.strip():
                raise ValueError("subject is required for email templates")
        else:
            if not has_text:
                raise ValueError("body_text is required for non-email templates")
            if self.body_html is not None:
                raise ValueError(
                    "body_html is only valid for email templates; "
                    f"got channel={self.channel.value}"
                )
            if self.subject is not None:
                raise ValueError(
                    f"subject is only valid for email templates; got channel={self.channel.value}"
                )
            if self.preview_text is not None:
                raise ValueError(
                    f"preview_text is only valid for email templates; got channel={self.channel.value}"
                )
        if self.whatsapp is not None and self.channel != ConversationChannel.whatsapp:
            raise ValueError(
                "whatsapp extension fields are only valid for whatsapp templates"
            )
        return self


class TemplateUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/templates/{id}`` (Step 3).

    All fields are optional — only those supplied are updated. The
    service enforces that channel cannot change after first save
    (different channels imply incompatible extension rows + variable
    sets). Subject/preview_text vs channel coherence is re-checked
    at the service layer against the persisted channel.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: TemplateCategory | None = None
    language: str | None = Field(default=None, min_length=2, max_length=16)
    body_text: str | None = Field(default=None, min_length=1, max_length=65535)
    # Campaigns v1 Step 04 — HTML body edits. Setting to an empty
    # string is not "clear" — the service treats it as an intentional
    # no-op edit; use PATCH with an omitted key to leave the current
    # HTML in place, or PATCH with a non-empty string to replace.
    body_html: str | None = Field(default=None, max_length=200_000)
    body_text_fallback_auto: bool | None = None
    subject: str | None = Field(default=None, max_length=998)
    preview_text: str | None = Field(default=None, max_length=190)
    change_note: str | None = Field(default=None, max_length=2000)
    # Meta-specific extras. Present only on WhatsApp templates; the
    # service rejects it on other channels. Sending the key with
    # ``None`` explicitly clears every WA field (idempotent no-op if
    # already null); omitting the key leaves the current values alone.
    whatsapp: WhatsAppExtensionPayload | None = None


# ---- Read / response shapes ------------------------------------------


class WhatsAppExtensionRead(BaseModel):
    """Snapshot of the WA-specific fields — populated on ``TemplateRead``
    for WhatsApp templates that have an extension row. Null on non-WA
    channels + on WA templates that haven't set any Meta-specific
    fields yet."""

    category: str | None = None
    header_type: str | None = None
    header_text: str | None = None
    footer_text: str | None = None
    buttons: list[WhatsAppTemplateButton] | None = None


class TemplateRead(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    channel: ConversationChannel
    name: str
    category: TemplateCategory
    language: str
    body_text: str
    # Campaigns v1 Step 04 — Email HTML body + auto-derive flag.
    # ``body_html`` is None for non-Email rows.
    body_html: str | None = None
    body_text_fallback_auto: bool = True
    subject: str | None
    preview_text: str | None
    variables: list[Any]
    internal_status: TemplateInternalStatus
    external_status: TemplateExternalStatus
    # Populated by the service layer for WA templates that carry an
    # extension row; ``None`` for other channels and for legacy WA
    # rows that pre-date extension writes.
    whatsapp: WhatsAppExtensionRead | None = None
    # Campaigns v1 Step 02 — Meta rejection reason surfaced inline in
    # the CRM library + campaign picker. Populated by the list endpoint
    # via a LEFT OUTER JOIN onto the WhatsApp extension row; single-
    # template read endpoints keep it at None (they don't drive the
    # rejection-tooltip UX).
    external_rejection_reason: str | None = None
    external_provider_id: str | None
    current_version: int
    created_by_user_id: uuid.UUID | None
    updated_by_user_id: uuid.UUID | None
    # Owner / Admin (or any role granted ``templates.activate``) can
    # flip this off to keep the row in the library for audit while
    # blocking every send path from picking it up. Defaults true so
    # every template is usable out of the box; existing rows are
    # backfilled true by the migration.
    is_active: bool = True
    # Latest approval / publish / rejection actor + timestamp. Populated
    # by the list + detail endpoints via a LATERAL join onto the review
    # audit trail so the SPA can render "Approved by X on Y" inline
    # without a per-row followup fetch. Null when the template has no
    # review history yet (fresh draft that was never submitted).
    last_reviewed_by_user_id: uuid.UUID | None = None
    last_reviewed_action: str | None = None
    last_reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TemplateVersionRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    body_text: str
    subject: str | None
    variables: list[Any]
    changed_by_user_id: uuid.UUID | None
    changed_at: datetime
    change_note: str | None


class TemplateReviewRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    reviewer_user_id: uuid.UUID | None
    action: TemplateReviewAction
    note: str | None
    created_at: datetime


class TemplateTestSendRead(ORMModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    channel: ConversationChannel
    sent_to: str
    sent_by_user_id: uuid.UUID | None
    channel_message_id: str | None
    sent_at: datetime


class WorkflowActionPayload(BaseModel):
    """Body for the five workflow-transition endpoints.

    ``note`` is mandatory for ``reject`` + ``request_changes`` —
    enforced at the workflow layer, not here, so a single Pydantic
    shape covers all five endpoints. The reject/request_changes
    handlers reject empty notes with 422.
    """

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    note: str | None = None


class TestSendPayload(BaseModel):
    """Body for ``POST /api/v1/templates/{id}/test-send``.

    ``recipient`` is the channel-shaped address (email for email
    templates, phone E.164-without-plus for WhatsApp / SMS, channel
    handle for FB / IG / push). ``sample_context`` overlays the
    default sample data so the operator can preview how a specific
    contact's variables render before going live.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recipient: str = Field(min_length=1, max_length=255)
    sample_context: dict[str, Any] | None = None
