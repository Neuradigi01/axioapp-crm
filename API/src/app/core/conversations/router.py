"""HTTP routes for the conversations engine.

  GET    /api/v1/conversations
  GET    /api/v1/conversations/{id}
  POST   /api/v1/conversations/{id}/messages
  PATCH  /api/v1/conversations/{id}
  POST   /api/v1/conversations/webhooks/{channel}

Reads need `conversations.read`; writes need `conversations.write`.
The webhook endpoint is intentionally unauthenticated (channel
providers don't carry JWTs) — adapter `parse_webhook` is the
signature-verification choke point.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
)
from src.app.core.conversations.schemas import (
    ConversationDetail,
    ConversationListResponse,
    ConversationOut,
    ConversationPatch,
    MessageOut,
    MessageSendPayload,
)
from src.app.core.conversations.service import (
    get_conversation,
    list_conversations,
    list_messages,
    patch_conversation,
    receive_webhook,
    send_outbound,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=ConversationListResponse)
async def list_endpoint(
    channel: Optional[ConversationChannel] = Query(default=None),
    status_: Optional[ConversationStatus] = Query(default=None, alias="status"),
    assigned_to: Optional[uuid.UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> ConversationListResponse:
    rows, total = await list_conversations(
        db,
        channel=channel,
        status_filter=status_,
        assigned_to_id=assigned_to,
        q=q,
        page=page,
        size=size,
    )
    return ConversationListResponse(
        items=[ConversationOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_detail_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> ConversationDetail:
    conv = await get_conversation(db, conversation_id)
    msgs = await list_messages(db, conversation_id)
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conv),
        messages=[MessageOut.model_validate(m) for m in msgs],
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message_endpoint(
    conversation_id: uuid.UUID,
    payload: MessageSendPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> MessageOut:
    msg = await send_outbound(
        db,
        conversation_id=conversation_id,
        user_id=user.id,
        text_body=payload.text,
        attachments=payload.attachments,
    )
    return MessageOut.model_validate(msg)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def patch_endpoint(
    conversation_id: uuid.UUID,
    payload: ConversationPatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.write")),
) -> ConversationOut:
    conv = await patch_conversation(
        db, conversation_id=conversation_id, payload=payload
    )
    return ConversationOut.model_validate(conv)


@router.post(
    "/webhooks/{channel}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def webhook_endpoint(
    channel: ConversationChannel,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    msg = await receive_webhook(db, channel=channel, payload=payload)
    return {"message_id": str(msg.id)}
