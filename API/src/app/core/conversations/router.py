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

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
)
from src.app.core.conversations.registry import (
    ChannelNotRegistered,
    resolve,
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
    # Widened to `str` so the sentinel value `'unassigned'` can pass
    # through (matches the leads / contacts convention). The service
    # parses the value: a UUID maps to equality; `'unassigned'` maps
    # to `IS NULL`; anything else is rejected with a 422-style error.
    assigned_to: Optional[str] = Query(default=None, max_length=64),
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
        assigned_to=assigned_to,
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
        user_id=user.legacy_uuid,
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


@router.get(
    "/webhooks/{channel}",
    response_class=PlainTextResponse,
)
async def webhook_verify_endpoint(
    channel: ConversationChannel,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Meta-style subscription handshake.

    Returns the value of `hub.challenge` (plain text) only when the
    `(mode, token)` pair authenticates against an org's stored
    verify_token. Channels without a per-org verify model fall back
    to the registry's adapter.

    For WhatsApp (Step 3.5.12) the verify token lives per-org in
    `whatsapp_account_configs`; we look it up there. Other channels
    still resolve a shared adapter from the registry."""
    qp = request.query_params
    mode = qp.get("hub.mode")
    token = qp.get("hub.verify_token")

    if channel == ConversationChannel.whatsapp:
        from src.app.core.integrations.whatsapp.connect import (
            find_org_by_verify_token,
        )

        if mode != "subscribe" or not token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="verify failed",
            )
        bundle = await find_org_by_verify_token(db, verify_token=token)
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="verify failed",
            )
        return PlainTextResponse(content=qp.get("hub.challenge", ""))

    try:
        adapter = resolve(channel)
    except ChannelNotRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    if not hasattr(adapter, "verify_subscription"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"channel '{channel.value}' has no subscription handshake",
        )
    if not adapter.verify_subscription(mode, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="verify failed"
        )
    return PlainTextResponse(content=qp.get("hub.challenge", ""))


@router.post(
    "/webhooks/{channel}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def webhook_endpoint(
    channel: ConversationChannel,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"webhook body is not valid JSON: {exc}",
        )

    # WhatsApp follows the per-org routing flow (Step 3.5.12) — extract
    # phone_id from the payload, look up the org's config, verify the
    # signature with that org's app_secret, then either dispatch to
    # the receive-message path or apply Meta status updates.
    if channel == ConversationChannel.whatsapp:
        return await _handle_whatsapp_webhook(db, raw=raw, payload=payload, request=request)

    # Other channels keep the registry-resolved adapter pattern.
    try:
        adapter = resolve(channel)
    except ChannelNotRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    if hasattr(adapter, "verify_signature"):
        signature = request.headers.get("x-hub-signature-256")
        if not adapter.verify_signature(raw, signature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid webhook signature",
            )
    try:
        msg = await receive_webhook(db, channel=channel, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return {"message_id": str(msg.id)}


async def _handle_whatsapp_webhook(
    db: AsyncSession,
    *,
    raw: bytes,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """WhatsApp-specific webhook handler with per-org credential routing.

    Sequence:
      1. Extract `phone_number_id` from the payload's metadata.
      2. Look up the org's WhatsApp account config — 404 if unknown.
      3. Verify the X-Hub-Signature-256 with the org's `app_secret`.
      4. Set the tenant context so downstream ORM queries respect RLS.
      5. Dispatch:
           - `statuses[]` present → update CampaignMessage rows.
           - `messages[]` present → fall through to `receive_webhook`.
    """
    from src.app.core.campaigns.service import apply_meta_status
    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppAdapter,
        parse_statuses,
    )
    from src.app.core.integrations.crypto import decrypt
    from src.app.core.integrations.whatsapp.connect import (
        find_org_by_phone_id,
    )
    from src.app.shared.context import RequestContext, set_context

    phone_id = _extract_phone_number_id(payload)
    if not phone_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing metadata.phone_number_id",
        )
    bundle = await find_org_by_phone_id(db, phone_id=phone_id)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no WhatsApp integration found for phone_id={phone_id}",
        )
    integration, config = bundle

    # Per-org signature verification.
    app_secret = decrypt(config.app_secret_enc)
    signature = request.headers.get("x-hub-signature-256")
    # Build a throwaway adapter just for the signature helper — it's a
    # pure HMAC check that doesn't touch any other instance state.
    adapter = WhatsAppAdapter(
        phone_id=config.phone_id,
        token="",  # unused for signature check
        app_secret=app_secret,
        verify_token=config.verify_token,
        api_version=config.api_version,
    )
    if not adapter.verify_signature(raw, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid webhook signature",
        )

    # Authenticated — set tenant context for downstream queries.
    set_context(RequestContext(org_id=integration.org_id, user_id=None))

    # Branch on payload shape: statuses[] update CampaignMessage rows
    # in place; messages[] flow through the existing inbound pipeline.
    status_events = parse_statuses(payload)
    if status_events:
        updated = 0
        for event in status_events:
            ok = await apply_meta_status(
                db,
                channel_message_id=event.channel_message_id,
                meta_status=event.status,
                timestamp=event.timestamp,
                error=event.error,
            )
            if ok:
                updated += 1
        return {"updated": updated}

    try:
        msg = await receive_webhook(
            db, channel=ConversationChannel.whatsapp, payload=payload
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return {"message_id": str(msg.id)}


def _extract_phone_number_id(payload: dict[str, Any]) -> str | None:
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        metadata = value.get("metadata") if isinstance(value, dict) else None
        if isinstance(metadata, dict):
            return str(metadata.get("phone_number_id") or "") or None
    except (KeyError, IndexError, TypeError):
        return None
    return None
