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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
    MessageDirection,
)
from src.app.shared.schemas import ORMModel, PaginatedResponse

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
    filename: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    caption: str | None = Field(default=None, max_length=1024)


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
    header: _InteractiveHeader | None = None
    footer: str | None = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


class CtaUrlPayload(BaseModel):
    """A single CTA button that opens a URL in the recipient's browser.

    Meta's ``cta_url`` interactive type. Restricted to one button (see
    ``_CTA_BUTTONS_MAX_COUNT`` rationale)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["cta_url"] = "cta_url"
    body: str = Field(min_length=1, max_length=_INTERACTIVE_BODY_MAX)
    button_text: str = Field(min_length=1, max_length=_BUTTON_TITLE_MAX)
    url: str = Field(min_length=1, max_length=_CTA_URL_MAX, pattern=r"^https?://.+")
    header: _InteractiveHeader | None = None
    footer: str | None = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


class _ListRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=_LIST_ROW_ID_MAX)
    title: str = Field(min_length=1, max_length=_LIST_ROW_TITLE_MAX)
    description: str | None = Field(default=None, max_length=_LIST_ROW_DESCRIPTION_MAX)


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
    sections: list[_ListSection] = Field(min_length=1, max_length=_LIST_SECTIONS_MAX_COUNT)
    header: _InteractiveHeader | None = None
    footer: str | None = Field(default=None, max_length=_INTERACTIVE_FOOTER_MAX)


InteractivePayload = Annotated[
    ReplyButtonsPayload | CtaUrlPayload | ListPayload,
    Field(discriminator="kind"),
]


class MessageSendPayload(BaseModel):
    text: str = Field(default="", max_length=4096)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    interactive: InteractivePayload | None = None
    # whatsapp-platform-upgrade Step 7: quoted reply. Optional UUID of
    # a previous message in the same conversation. Service resolves it
    # to the channel's wamid before calling the adapter; mismatch
    # (wrong conv / no channel_message_id yet) surfaces as 400.
    reply_to_message_id: uuid.UUID | None = None
    # whatsapp-platform-upgrade Step 27a — multi-number per org.
    # When set, the composer pins the outbound to a specific
    # connected phone instead of defaulting to whichever number
    # the conversation arrived on. NULL preserves the legacy
    # behaviour for every single-number org.
    send_from_phone_id: str | None = Field(default=None, max_length=64)


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
    def _check_color_in_palette(self) -> TagCreate:
        if self.color not in _TAG_COLORS:
            raise ValueError(f"color must be one of: {sorted(_TAG_COLORS)}")
        return self


class TagUpdate(BaseModel):
    """Body of ``PATCH /api/v1/conversations/tags/{id}``. Both fields
    optional — only supplied keys are applied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _check_color(self) -> TagUpdate:
        if self.color is not None and self.color not in _TAG_COLORS:
            raise ValueError(f"color must be one of: {sorted(_TAG_COLORS)}")
        return self


class TagOut(ORMModel):
    id: uuid.UUID
    name: str
    color: str
    created_by_user_id: uuid.UUID | None = None
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


class EmailReplyPayload(BaseModel):
    """Body of ``POST /api/v1/conversations/{id}/email-reply`` — the
    email-channel counterpart to the generic ``/messages`` send. Email
    needs ``subject`` + a chosen ``account_id`` that the generic
    payload doesn't carry; this schema layers those on top. Both are
    optional — the service defaults ``account_id`` to the sender's
    first ``live`` connected mailbox and derives ``subject`` from the
    thread when omitted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body_text: str = Field(min_length=1, max_length=65536)
    body_html: str | None = Field(default=None, max_length=131072)
    subject: str | None = Field(default=None, max_length=512)
    account_id: uuid.UUID | None = None


class SendTemplatePayload(BaseModel):
    """Body of ``POST /api/v1/conversations/{id}/messages/template``.

    Sends an approved WhatsApp template through the conversation's
    active adapter. Used by the inbox composer's inline template
    picker when the 24-hour session has expired — Meta's rule is that
    templates are the only sendable message type outside the window.

    ``variables`` maps ``{{n}}`` placeholder index (1-based) to a
    plaintext value. Keys are strings on the wire (JSON object keys
    are always strings); the service parses them back to ints before
    handing to the adapter."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    template_id: uuid.UUID
    variables: dict[str, str] = Field(default_factory=dict)
    send_from_phone_id: str | None = Field(default=None, max_length=64)


class ReactionRequest(BaseModel):
    """Body of ``POST /conversations/{id}/messages/{message_id}/reactions``.

    `emoji` is a single-grapheme string (Meta enforces "one Unicode
    emoji" — we don't try to validate the grapheme cluster here, the
    Cloud API does it). Empty/null `emoji` removes the caller's
    existing reaction (WhatsApp's documented "send empty reaction
    to remove" pattern)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    emoji: str | None = Field(default=None, max_length=16)


class ConversationPatch(BaseModel):
    assigned_to_id: uuid.UUID | None = None
    status: ConversationStatus | None = None
    ai_handling: bool | None = None
    # Only meaningful with ``status="snoozed"``: reopen automatically at
    # this instant. Omitted / null = snoozed until the customer replies.
    snoozed_until: datetime | None = None


# Hard cap on one bulk request — the inbox list pages at 50 and never
# loads more than a few pages at a time.
BULK_MAX_CONVERSATIONS = 200

BulkAction = Literal[
    "close",
    "reopen",
    "snooze",
    "mark_read",
    "mark_unread",
    "assign",
    "add_tag",
]


class ConversationBulkRequest(BaseModel):
    """Body of ``POST /api/v1/conversations/bulk``. One action applied to
    every listed conversation the caller may act on; rows the caller
    can't touch are skipped (reported back), never a whole-request 403."""

    model_config = ConfigDict(extra="forbid")

    conversation_ids: list[uuid.UUID] = Field(min_length=1, max_length=BULK_MAX_CONVERSATIONS)
    action: BulkAction
    # ``assign`` — target user (null = unassign).
    assigned_to_id: uuid.UUID | None = None
    # ``add_tag`` — tag to attach.
    tag_id: uuid.UUID | None = None
    # ``snooze`` — optional wake-up time.
    snoozed_until: datetime | None = None

    @model_validator(mode="after")
    def _check_action_args(self) -> ConversationBulkRequest:
        if self.action == "add_tag" and self.tag_id is None:
            raise ValueError("tag_id is required for add_tag.")
        return self


class ConversationBulkSkipped(BaseModel):
    id: uuid.UUID
    reason: str


class ConversationBulkResult(BaseModel):
    updated: int
    skipped: list[ConversationBulkSkipped] = Field(default_factory=list)


class ConversationCounts(BaseModel):
    """Unread badge counts for the inbox filter chips. Each value is the
    number of conversations with at least one unread message (not the
    message total), excluding closed conversations."""

    all: int
    mine: int
    unassigned: int
    by_channel: dict[str, int] = Field(default_factory=dict)


_SHORTCUT_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"


class SavedReplyCreate(BaseModel):
    """Body of ``POST /api/v1/conversations/saved-replies``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4096)
    # Lower-case keyword typed after ``/`` in the composer, e.g. ``price``.
    shortcut: str | None = Field(default=None, pattern=_SHORTCUT_PATTERN)


class SavedReplyUpdate(BaseModel):
    """Body of ``PATCH /api/v1/conversations/saved-replies/{id}``. Only
    supplied keys change; send ``shortcut: null`` to clear it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=4096)
    shortcut: str | None = Field(default=None, pattern=_SHORTCUT_PATTERN)


class SavedReplyOut(ORMModel):
    id: uuid.UUID
    title: str
    body: str
    shortcut: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationContactSet(BaseModel):
    """Attach a contact to a conversation from the inbox details rail.
    Exactly one of:

    * ``contact_id`` — link an existing contact;
    * ``full_name`` — save the conversation's sender as a new contact
      (phone / email taken from the conversation's ``external_id``).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: uuid.UUID | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _exactly_one(self) -> ConversationContactSet:
        if (self.contact_id is None) == (self.full_name is None):
            raise ValueError("Provide exactly one of contact_id or full_name.")
        return self


class ConversationCreate(BaseModel):
    """Operator-initiated fresh thread. The service resolves the
    contact's phone (WhatsApp/SMS) or email (Email) as the external_id
    and reuses the existing find-or-create path — starting a thread
    for a contact that already has one just returns the existing row."""

    model_config = ConfigDict(extra="forbid")

    channel: ConversationChannel
    contact_id: uuid.UUID


class ConversationOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    channel: ConversationChannel
    external_id: str
    contact_id: uuid.UUID | None
    assigned_to_id: uuid.UUID | None
    status: ConversationStatus
    ai_handling: bool
    # tasks/ai-assistants-omnichannel Step 3 — human-takeover state.
    # ``ai_paused=false`` = AI is (or would be) auto-answering; ``true``
    # = a human took over and AI is silent on this thread until Resume.
    ai_paused: bool = False
    ai_paused_by_user_id: uuid.UUID | None = None
    ai_paused_at: datetime | None = None
    # True when AI will actually answer this conversation on the next
    # inbound — matches the server-side ``should_pause`` rule in
    # ``send_outbound``: NOT paused AND (per-conversation
    # ``ai_handling`` flag OR the org has an active assistant bound
    # to this channel). Populated by the list + detail endpoints from
    # a single per-request lookup of the org's active bound-channel
    # set, so no N+1. Frontend uses this to decide whether to render
    # the "🤖 AI is handling" banner — without it the banner shows on
    # every AI-capable channel regardless of real state.
    ai_active: bool = False
    last_message_at: datetime | None
    # Short preview of the most recent external message (whitespace-collapsed
    # + trimmed to 140 chars server-side). Populated only by the list
    # endpoint via ``bulk_last_message_body_for_conversations`` so the
    # inbox row can render a snippet without a per-row fetch; the detail
    # endpoint leaves this ``None`` (the thread pane loads full messages).
    # Internal notes are excluded from the preview so the customer-facing
    # snippet reflects what was actually exchanged externally.
    last_message_body: str | None = None
    # List-only: who sent the latest external message. ``"in"`` means the
    # customer is waiting on a reply (drives the "Waiting 2h" indicator).
    last_message_direction: Literal["in", "out"] | None = None
    # Last inbound customer message — the "waiting since" anchor and the
    # WhatsApp 24h-window pivot.
    last_customer_message_at: datetime | None = None
    # Timed snooze wake-up; null when not snoozed or snoozed until reply.
    snoozed_until: datetime | None = None
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
    acquisition_source: str | None = None
    acquisition_campaign_id: str | None = None
    acquisition_ad_id: str | None = None
    # Step 27a — Meta phone-id the conversation arrived on. NULL
    # for legacy conversations. The composer reads this to default
    # "Send from" back to the same number.
    received_via_phone_id: str | None = None


class ConversationAttributionOut(BaseModel):
    """Detailed attribution surface for the chat-thread chip + Meta
    Ads Manager deeplink (whatsapp-platform-upgrade Step 24).

    ``deeplink`` is built server-side via
    :func:`ads_lookup.deeplink_for_ad` so the SPA doesn't have to
    encode Meta's URL format. ``payload`` is the raw referral
    envelope as captured from Meta + the resolved campaign
    metadata under ``_resolved``."""

    conversation_id: uuid.UUID
    source: str | None
    campaign_id: str | None
    campaign_name: str | None
    ad_id: str | None
    ad_name: str | None
    landing_url: str | None
    deeplink: str | None
    payload: dict[str, Any] = Field(default_factory=dict)


ConversationListResponse = PaginatedResponse[ConversationOut]


class MessageOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    conversation_id: uuid.UUID
    direction: MessageDirection
    sender_user_id: uuid.UUID | None
    text: str | None
    attachments: list[dict[str, Any]]
    # Outbound interactive envelope (whatsapp-platform-upgrade Step 6).
    # The inbox bubble renders buttons / list rows from this dict; the
    # raw shape mirrors what the operator built in the composer.
    interactive_payload: dict[str, Any] | None = None
    # whatsapp-platform-upgrade Step 7: quoted-reply target + the
    # reaction list applied to this message by its viewers. `reactions`
    # entries are `{user, emoji, ts}` dicts — see `core/conversations/
    # service._apply_reaction` for write rules.
    reply_to_message_id: uuid.UUID | None = None
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
    channel_message_id: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
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
    expires_at: datetime | None = None
    hours_remaining: float = 0.0
    last_customer_message_at: datetime | None = None


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    # Step 15 — populated only for WhatsApp conversations. NULL on
    # every other channel (no session-window concept). The banner
    # component renders nothing when this is None.
    whatsapp_session_state: WhatsAppSessionState | None = None
