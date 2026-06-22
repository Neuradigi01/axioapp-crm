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

from pydantic import BaseModel, ConfigDict, Field

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
    channel_message_id: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    read_at: Optional[datetime]
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
