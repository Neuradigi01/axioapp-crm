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
from typing import Any, Literal, Optional

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


class MessageSendPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


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
    channel_message_id: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    read_at: Optional[datetime]
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
