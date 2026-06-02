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
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import PaginatedResponse
from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
    MessageDirection,
)


class MessageSendPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ConversationPatch(BaseModel):
    assigned_to_id: Optional[uuid.UUID] = None
    status: Optional[ConversationStatus] = None
    ai_handling: Optional[bool] = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
