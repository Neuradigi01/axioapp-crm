"""Pydantic v2 schemas for the conversations engine.

Everything below the `MessageSendPayload` / `ConversationPatch` line is
read-side. Writes are intentionally narrow:

- `MessageSendPayload` — outbound from CRM (admin/agent typed) — the
  service resolves the channel adapter and persists the row.
- `ConversationPatch` — only the three fields an inbox triages
  (`assigned_to_id`, `status`, `ai_handling`). No way to retroactively
  rewrite history.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.shared.schemas import ORMModel, PaginatedResponse
from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
    MessageDirection,
)


AttachmentType = Literal["image", "video", "audio", "document"]


class AttachmentPayload(BaseModel):
    """Structured attachment descriptor produced by the media-upload
    pipeline. Stored verbatim on ``Message.attachments`` and rendered
    in the inbox thread.

    ``media_id`` is Meta's identifier returned from
    ``POST /{phone_id}/media``; ``caption`` is folded into the
    outbound envelope by the WhatsApp adapter (silently dropped for
    audio per Meta's spec). The remaining fields are display
    metadata the inbox thread uses to render a file card without
    re-querying Meta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: AttachmentType
    media_id: str = Field(min_length=1, max_length=128)
    mime_type: str = Field(min_length=1, max_length=128)
    filename: Optional[str] = Field(default=None, max_length=255)
    size_bytes: Optional[int] = Field(default=None, ge=0)
    caption: Optional[str] = Field(default=None, max_length=1024)


# --- Interactive messages (whatsapp-platform-upgrade Step 6) ----------
#
# Meta-published limits the schema enforces at the boundary so a bad
# build never reaches the Cloud API. These match the documented caps
# at developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
# /interactive-messages. Tighten if Meta tightens; the builder reads
# these via the API too.


_INTERACTIVE_HEADER_MAX = 60
_INTERACTIVE_BODY_MAX = 1024
_INTERACTIVE_FOOTER_MAX = 60

_BUTTON_TITLE_MAX = 20
_BUTTON_ID_MAX = 256
_BUTTONS_MAX_COUNT = 3

# CTA buttons are capped at 2 by Meta but the spec narrows to 1 to
# stay safe (some renderers misbehave on the second). Re-evaluate
# once an iOS + Android smoke shows two-button CTA renders cleanly.
_CTA_BUTTONS_MAX_COUNT = 1
_CTA_URL_MAX = 2000
_CTA_PHONE_MAX = 20

_LIST_BUTTON_TEXT_MAX = 20
_LIST_SECTION_TITLE_MAX = 24
_LIST_ROW_TITLE_MAX = 24
_LIST_ROW_DESCRIPTION_MAX = 72
_LIST_ROW_ID_MAX = 200
_LIST_ROWS_MAX_COUNT = 10
_LIST_SECTIONS_MAX_COUNT = 10


class _InteractiveHeader(BaseModel):
    """Optional one-line header above the body. Only TEXT is supported
    here; media headers are a Step-25 surface."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=_INTERACTIVE_HEADER_MAX)


class _ReplyButton(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=_BUTTON_ID_MAX)
    title: str = Field(min_length=1, max_length=_BUTTON_TITLE_MAX)


class ReplyButtonsPayload(BaseModel):
    """Up to 3 quick-reply buttons. Meta delivers a ``button_reply``
    event when the recipient taps; the webhook parser maps that back
    onto the original button's ``id`` for routing."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["reply_buttons"] = "reply_buttons"
    body: str = Field(min_length=1, max_length=_INTERACTIVE_BODY_MAX)
    buttons: list[_ReplyButton] = Field(min_length=1, max_length=_BUTTONS_MAX_COUNT)
    header: Optional[_InteractiveHeader] = None
    footer: Optional[str] = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


class CtaUrlPayload(BaseModel):
    """A single CTA button that opens a URL in the recipient's browser.

    Meta's ``cta_url`` interactive type. Restricted to one button (see
    ``_CTA_BUTTONS_MAX_COUNT`` rationale)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["cta_url"] = "cta_url"
    body: str = Field(min_length=1, max_length=_INTERACTIVE_BODY_MAX)
    button_text: str = Field(min_length=1, max_length=_BUTTON_TITLE_MAX)
    url: str = Field(min_length=1, max_length=_CTA_URL_MAX, pattern=r"^https?://.+")
    header: Optional[_InteractiveHeader] = None
    footer: Optional[str] = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


class _ListRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=_LIST_ROW_ID_MAX)
    title: str = Field(min_length=1, max_length=_LIST_ROW_TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=_LIST_ROW_DESCRIPTION_MAX)


class _ListSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=_LIST_SECTION_TITLE_MAX)
    rows: list[_ListRow] = Field(min_length=1, max_length=_LIST_ROWS_MAX_COUNT)


class ListPayload(BaseModel):
    """Bottom-sheet list — up to 10 rows split across sections. Meta
    delivers a ``list_reply`` event carrying the tapped row's id."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["list"] = "list"
    body: str = Field(min_length=1, max_length=_INTERACTIVE_BODY_MAX)
    button_text: str = Field(min_length=1, max_length=_LIST_BUTTON_TEXT_MAX)
    sections: list[_ListSection] = Field(
        min_length=1, max_length=_LIST_SECTIONS_MAX_COUNT
    )
    header: Optional[_InteractiveHeader] = None
    footer: Optional[str] = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


InteractivePayload = Annotated[
    ReplyButtonsPayload | CtaUrlPayload | ListPayload,
    Field(discriminator="kind"),
]


class MessageSendPayload(BaseModel):
    text: str = Field(default="", max_length=4096)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    interactive: Optional[InteractivePayload] = None
    # whatsapp-platform-upgrade Step 7: quoted reply. Optional UUID of
    # a previous message in the same conversation. Service resolves it
    # to the channel's wamid before calling the adapter; mismatch
    # (wrong conv / no channel_message_id yet) surfaces as 400.
    reply_to_message_id: Optional[uuid.UUID] = None


# --- Tags (whatsapp-platform-upgrade Step 14) ------------------------


# Fixed palette — keys map to Tailwind class sets on the frontend
# (`bg-{color}-100 text-{color}-700 ring-{color}-200`). The list is
# explicit (not free-form hex) so the picker can't ship low-contrast
# colors. Add to this set before adding to the picker.
_TAG_COLORS = {
    "zinc",
    "rose",
    "amber",
    "yellow",
    "lime",
    "emerald",
    "teal",
    "sky",
    "blue",
    "indigo",
    "violet",
    "fuchsia",
}


class TagCreate(BaseModel):
    """Body of ``POST /api/v1/conversations/tags``.

    Names are trimmed + case-insensitively unique per-org (DB-level
    enforcement via the `uq_conv_tags_org_lower_name` functional
    index)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    color: str = Field(default="zinc", max_length=16)

    @model_validator(mode="after")
    def _check_color_in_palette(self) -> "TagCreate":
        if self.color not in _TAG_COLORS:
            raise ValueError(
                f"color must be one of: {sorted(_TAG_COLORS)}"
            )
        return self


class TagUpdate(BaseModel):
    """Body of ``PATCH /api/v1/conversations/tags/{id}``. Both fields
    optional — only supplied keys are applied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    color: Optional[str] = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _check_color(self) -> "TagUpdate":
        if self.color is not None and self.color not in _TAG_COLORS:
            raise ValueError(
                f"color must be one of: {sorted(_TAG_COLORS)}"
            )
        return self


class TagOut(ORMModel):
    id: uuid.UUID
    name: str
    color: str
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    # Populated by `list_tags` (count of assignments). Defaults to 0
    # when read via the per-conversation embed.
    usage_count: int = 0


class AssignTagRequest(BaseModel):
    """Body of ``POST /api/v1/conversations/{id}/tags``."""

    model_config = ConfigDict(extra="forbid")

    tag_id: uuid.UUID


class NoteCreate(BaseModel):
    """Body of ``POST /api/v1/conversations/{id}/notes``.

    Internal-only message — never dispatched to the channel. `mentions`
    is capped at 5 ids to bound notification fanout (Step 13's risk:
    spammy @-group calls). The router rejects ids that aren't org
    members at insert time."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=4096)
    mentions: list[uuid.UUID] = Field(default_factory=list, max_length=5)


class ReactionRequest(BaseModel):
    """Body of ``POST /conversations/{id}/messages/{message_id}/reactions``.

    `emoji` is a single-grapheme string (Meta enforces "one Unicode
    emoji" — we don't try to validate the grapheme cluster here, the
    Cloud API does it). Empty/null `emoji` removes the caller's
    existing reaction (WhatsApp's documented "send empty reaction
    to remove" pattern)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    emoji: Optional[str] = Field(default=None, max_length=16)


class ConversationPatch(BaseModel):
    assigned_to_id: Optional[uuid.UUID] = None
    status: Optional[ConversationStatus] = None
    ai_handling: Optional[bool] = None


class ConversationOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    channel: ConversationChannel
    external_id: str
    contact_id: Optional[uuid.UUID]
    assigned_to_id: Optional[uuid.UUID]
    status: ConversationStatus
    ai_handling: bool
    last_message_at: Optional[datetime]
    unread_count: int
    created_at: datetime
    # Step 14 — assigned tags as embedded `{id, name, color}` triples.
    # Populated by the list / detail services; defaults to empty when
    # not selected for performance.
    tags: list[dict[str, Any]] = Field(default_factory=list)
    # Step 24 — click-to-WhatsApp ad attribution. Slim trio on the
    # list / detail payload so the chip can render without a
    # second fetch; the full referral envelope ships from
    # `GET /{id}/attribution`.
    acquisition_source: Optional[str] = None
    acquisition_campaign_id: Optional[str] = None
    acquisition_ad_id: Optional[str] = None


class ConversationAttributionOut(BaseModel):
    """Detailed attribution surface for the chat-thread chip + Meta
    Ads Manager deeplink (whatsapp-platform-upgrade Step 24).

    ``deeplink`` is built server-side via
    :func:`ads_lookup.deeplink_for_ad` so the SPA doesn't have to
    encode Meta's URL format. ``payload`` is the raw referral
    envelope as captured from Meta + the resolved campaign
    metadata under ``_resolved``."""

    conversation_id: uuid.UUID
    source: Optional[str]
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    ad_id: Optional[str]
    ad_name: Optional[str]
    landing_url: Optional[str]
    deeplink: Optional[str]
    payload: dict[str, Any] = Field(default_factory=dict)


ConversationListResponse = PaginatedResponse[ConversationOut]


class MessageOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    conversation_id: uuid.UUID
    direction: MessageDirection
    sender_user_id: Optional[uuid.UUID]
    text: Optional[str]
    attachments: list[dict[str, Any]]
    # Outbound interactive envelope (whatsapp-platform-upgrade Step 6).
    # The inbox bubble renders buttons / list rows from this dict; the
    # raw shape mirrors what the operator built in the composer.
    interactive_payload: Optional[dict[str, Any]] = None
    # whatsapp-platform-upgrade Step 7: quoted-reply target + the
    # reaction list applied to this message by its viewers. `reactions`
    # entries are `{user, emoji, ts}` dicts — see `core/conversations/
    # service._apply_reaction` for write rules.
    reply_to_message_id: Optional[uuid.UUID] = None
    reactions: list[dict[str, Any]] = Field(default_factory=list)
    # whatsapp-platform-upgrade Step 13 — internal notes flag +
    # @mentions. The frontend renders is_internal=true with yellow
    # styling and an "Internal note" label; mentioned_user_ids drives
    # the notification fanout at insert time.
    is_internal: bool = False
    mentioned_user_ids: list[uuid.UUID] = Field(default_factory=list)
    # whatsapp-platform-upgrade Step 19 — derived from
    # `payload['author']` on the ORM row. Frontend renders a small
    # "🤖 AI" badge on the bubble. Defaults False for human +
    # auto-reply + keyword-rule messages.
    is_ai: bool = False
    channel_message_id: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    read_at: Optional[datetime]
    created_at: datetime


class WhatsAppSessionState(BaseModel):
    """24-hour session window read shape
    (whatsapp-platform-upgrade Step 15).

    Computed server-side from `Conversation.last_customer_message_at`
    on every detail fetch. `expires_at` is the absolute UTC timestamp
    the window closes; `hours_remaining` is a float for easy
    frontend rendering ("4h 12m" → derive minutes from the fractional
    part). Both are 0 / None when out of session."""

    in_session: bool
    expires_at: Optional[datetime] = None
    hours_remaining: float = 0.0
    last_customer_message_at: Optional[datetime] = None


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    # Step 15 — populated only for WhatsApp conversations. NULL on
    # every other channel (no session-window concept). The banner
    # component renders nothing when this is None.
    whatsapp_session_state: Optional[WhatsAppSessionState] = None
