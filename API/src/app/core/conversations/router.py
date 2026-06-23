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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.media_upload import (
    MAX_CAPTION_LENGTH,
    MediaUploadError,
    captions_supported,
    upload_to_meta,
    validate_attachment,
)
from src.app.core.conversations.models import (
    ConversationChannel,
    ConversationStatus,
)
from src.app.core.conversations.registry import (
    ChannelNotRegistered,
    resolve,
)
from src.app.core.conversations.notes_service import post_note
from src.app.core.conversations.schemas import (
    AttachmentType,
    ConversationDetail,
    ConversationListResponse,
    ConversationOut,
    ConversationPatch,
    MessageOut,
    MessageSendPayload,
    NoteCreate,
    ReactionRequest,
)
from src.app.core.conversations.service import (
    get_conversation,
    list_conversations,
    list_messages,
    patch_conversation,
    react_to_message,
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
    # Must carry at least one of the three payloads — the schema relaxed
    # `text` to optional to allow interactive-only sends, so re-check at
    # the boundary instead of with a Pydantic root validator (keeps the
    # error message friendlier).
    if (
        not payload.text
        and not payload.attachments
        and payload.interactive is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Message must include text, an attachment, or an "
                "interactive payload."
            ),
        )
    interactive_dict = (
        payload.interactive.model_dump(mode="json")
        if payload.interactive is not None
        else None
    )
    try:
        msg = await send_outbound(
            db,
            conversation_id=conversation_id,
            user_id=user.legacy_uuid,
            text_body=payload.text,
            attachments=payload.attachments,
            interactive=interactive_dict,
            reply_to_message_id=payload.reply_to_message_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/notes",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_note_endpoint(
    conversation_id: uuid.UUID,
    payload: NoteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> MessageOut:
    """Post an internal-only note to the conversation
    (whatsapp-platform-upgrade Step 13).

    Notes never reach the customer — they're operator-only annotations
    rendered yellow in the thread. Mentions in `payload.mentions` fan
    out one in-app notification per id; the schema caps the list at
    5 to bound notification spam from group calls."""
    msg = await post_note(
        db,
        conversation_id=conversation_id,
        author_id=user.legacy_uuid,
        text=payload.text,
        mentioned_user_ids=payload.mentions,
    )
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/messages/{message_id}/reactions",
    response_model=MessageOut,
)
async def react_endpoint(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: ReactionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> MessageOut:
    """React to a message with a single emoji (Step 7).

    Sending an empty / null `emoji` removes the caller's reaction —
    matches Meta's documented Cloud-API pattern. Returns the target
    message row with its updated `reactions` JSONB so the SPA can swap
    the bubble's reaction badge without a follow-up fetch."""
    try:
        msg = await react_to_message(
            db,
            conversation_id=conversation_id,
            message_id=message_id,
            user_id=user.legacy_uuid,
            emoji=payload.emoji,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/messages/media",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_media_message_endpoint(
    conversation_id: uuid.UUID,
    file: UploadFile = File(...),
    type: AttachmentType = Form(...),
    caption: Optional[str] = Form(default=None, max_length=MAX_CAPTION_LENGTH),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> MessageOut:
    """Outbound media message for WhatsApp conversations (Step 5 of
    whatsapp-platform-upgrade).

    The browser uploads the binary in a multipart envelope; the server
    streams it once into memory, validates MIME + size against Meta's
    documented per-type caps, uploads to ``POST /{phone_id}/media``,
    and ships the resulting ``media_id`` to the recipient via the
    standard ``send_outbound`` pipeline (which writes the row + emits
    the activity log + bumps the conversation's last_message_at).

    Currently WhatsApp-only — other channels (web/email/sms) have no
    Meta-style media-id flow; expand the conversation lookup branch
    below when a second channel needs it."""
    conv = await get_conversation(db, conversation_id)
    if conv.channel != ConversationChannel.whatsapp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Media messages are only supported on WhatsApp "
                f"conversations (got {conv.channel.value!r})."
            ),
        )

    mime_type = (file.content_type or "").lower()
    file_bytes = await file.read()
    try:
        validate_attachment(
            type_=type,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
        )
    except MediaUploadError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=exc.user_message
        )

    try:
        bundle = await resolve_whatsapp_adapter(db)
    except WhatsAppNotConnected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )

    # Resolve the per-org Cloud API credentials. The adapter holds them
    # in private attrs; we read directly because the upload uses the
    # SAME phone_id + token that the send call will use a moment later.
    phone_id = getattr(bundle, "_phone_id", None)
    token = getattr(bundle, "_token", None)
    api_version = getattr(bundle, "_api_version", None)
    if not phone_id or not token or not api_version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WhatsApp adapter is in an unexpected state.",
        )

    try:
        media_id = await upload_to_meta(
            phone_id=phone_id,
            token=token,
            api_version=api_version,
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=file.filename or "file",
        )
    except MediaUploadError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=exc.user_message
        )

    effective_caption = caption if captions_supported(type) else None

    attachment_record = {
        "type": type,
        "media_id": media_id,
        "mime_type": mime_type,
        "filename": file.filename,
        "size_bytes": len(file_bytes),
        "caption": effective_caption,
    }
    text_body = effective_caption or ""
    # `send_outbound` requires non-empty text for the activity-log
    # preview + the row's `text` column. Use the media type as a stable
    # fallback when no caption was supplied so the inbox doesn't render
    # an empty row.
    if not text_body:
        text_body = f"[{type}]"

    msg = await send_outbound(
        db,
        conversation_id=conversation_id,
        user_id=user.legacy_uuid,
        text_body=text_body,
        attachments=[attachment_record],
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
    # Reaction events return None — the row update is enough; the SPA
    # picks up the change on the next thread poll / WS push.
    if msg is None:
        return {"reaction_applied": True}
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
      1. Detect template-status events (route via WABA id) OR extract
         `phone_number_id` from the payload's metadata.
      2. Look up the org's WhatsApp account config — 404 if unknown.
      3. Verify the X-Hub-Signature-256 with the org's `app_secret`.
      4. Set the tenant context so downstream ORM queries respect RLS.
      5. Dispatch:
           - `message_template_status_update` field → templates_service
           - `statuses[]` present → update CampaignMessage rows.
           - `messages[]` present → fall through to `receive_webhook`.
    """
    from config import WHATSAPP_APP_SECRET
    from src.app.core.campaigns.service import apply_meta_status
    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppAdapter,
        parse_statuses,
    )
    from src.app.core.integrations.crypto import decrypt
    from src.app.core.integrations.whatsapp.connect import (
        find_org_by_phone_id,
        find_org_by_waba_id,
    )
    from src.app.shared.context import RequestContext, set_context

    # whatsapp-platform-upgrade Step 12 — phone quality events. Same
    # shape as template-status events: discriminated by
    # `changes[0].field`. Routed via WABA id (entry.id) because the
    # phone metadata isn't carried on these payloads.
    quality_event = _extract_phone_quality_event(payload)
    if quality_event is not None:
        bundle = await find_org_by_waba_id(
            db, waba_id=quality_event["waba_id"]
        )
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no WhatsApp integration found for "
                    f"waba_id={quality_event['waba_id']}"
                ),
            )
        integration, config = bundle
        _verify_whatsapp_signature(
            raw=raw,
            signature_header=request.headers.get("x-hub-signature-256"),
            config=config,
            platform_secret=WHATSAPP_APP_SECRET,
        )
        set_context(
            RequestContext(org_id=integration.org_id, user_id=None)
        )
        from src.app.core.integrations.whatsapp.health_service import (
            apply_webhook_quality_event,
        )

        # Use the resolved config's phone_id rather than the webhook's
        # display_phone_number — the lookup column is the Meta-side
        # opaque id, not the E.164 string. Phase-9 multi-number per
        # WABA will need to disambiguate by display_phone_number; for
        # the single-phone-per-WABA case (current scope) this is fine.
        applied = await apply_webhook_quality_event(
            db,
            org_id=integration.org_id,
            phone_id=config.phone_id,
            new_quality=quality_event.get("event"),
            new_tier=quality_event.get("current_limit"),
            occurred_at=quality_event.get("occurred_at"),
        )
        return {"phone_quality_applied": applied}

    # whatsapp-platform-upgrade Step 8 — template status events carry
    # no `metadata.phone_number_id`. Route by `entry[0].id` (WABA id)
    # before the phone-id branch.
    template_event = _extract_template_status_event(payload)
    if template_event is not None:
        bundle = await find_org_by_waba_id(
            db, waba_id=template_event["waba_id"]
        )
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no WhatsApp integration found for "
                    f"waba_id={template_event['waba_id']}"
                ),
            )
        integration, config = bundle
        _verify_whatsapp_signature(
            raw=raw,
            signature_header=request.headers.get("x-hub-signature-256"),
            config=config,
            platform_secret=WHATSAPP_APP_SECRET,
        )
        set_context(
            RequestContext(org_id=integration.org_id, user_id=None)
        )
        from src.app.core.integrations.whatsapp.templates_service import (
            apply_template_status_update,
        )

        applied = await apply_template_status_update(
            db,
            org_id=integration.org_id,
            meta_template_id=template_event.get("message_template_id"),
            template_name=template_event.get("message_template_name"),
            language=template_event.get("message_template_language"),
            event=template_event["event"],
            reason=template_event.get("reason"),
        )
        return {"template_status_applied": applied}

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

    # Signature verification — prefer the env-side platform secret
    # (set when the deploy is using Embedded Signup, whatsapp-platform-
    # upgrade Step 2), fall back to the per-org `app_secret_enc` that
    # the legacy manual-connect flow wrote. Orgs that connected before
    # ES landed keep working without an env var being set.
    app_secret = WHATSAPP_APP_SECRET
    if not app_secret:
        if not config.app_secret_enc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "WhatsApp signature secret is not configured for "
                    "this org and no platform-level WHATSAPP_APP_SECRET "
                    "is set."
                ),
            )
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
    if msg is None:
        return {"reaction_applied": True}
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


def _extract_phone_quality_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Detect + parse a ``phone_number_quality_update`` webhook event
    (whatsapp-platform-upgrade Step 12).

    Meta delivers these with ``changes[0].field`` =
    ``phone_number_quality_update``. The ``value`` carries the new
    quality rating + (occasionally) the messaging-limit tier. Phone
    routing key is ``value.display_phone_number`` (full E.164
    string), but the simpler dispatch key is ``entry[0].id`` (WABA
    id) so we use that to look up the org.

    Returns a dict ``{waba_id, phone_id, event, current_limit,
    occurred_at}`` or None when the payload isn't a quality event."""
    from datetime import datetime, timezone

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(change, dict):
        return None
    if change.get("field") != "phone_number_quality_update":
        return None
    value = change.get("value")
    if not isinstance(value, dict):
        return None
    event = value.get("event")
    if not isinstance(event, str) or not event:
        return None
    raw_phone = value.get("display_phone_number") or value.get("phone_number")
    phone_id = (
        str(raw_phone) if isinstance(raw_phone, (str, int)) else ""
    )
    if not phone_id:
        return None
    occurred_at: datetime | None = None
    raw_ts = value.get("timestamp") or entry.get("time")
    if isinstance(raw_ts, (int, float)):
        try:
            occurred_at = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
        except (TypeError, ValueError):
            occurred_at = None
    return {
        "waba_id": str(entry.get("id") or "") or None,
        "phone_id": phone_id,
        "event": event,
        "current_limit": (
            value.get("current_limit")
            if isinstance(value.get("current_limit"), str)
            else None
        ),
        "occurred_at": occurred_at,
    }


def _extract_template_status_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Detect + parse a ``message_template_status_update`` webhook event
    (whatsapp-platform-upgrade Step 8).

    Meta delivers these alongside inbound messages on the same
    callback URL; the discriminator is ``entry[0].changes[0].field``.
    The change's ``value`` carries the template id + status event +
    optional rejection reason. ``entry[0].id`` is the WABA id (the
    template routing key — there's no phone-number metadata on these
    payloads).

    Returns a dict ``{waba_id, event, message_template_id,
    message_template_name, message_template_language, reason}`` or
    None when the payload isn't a template-status event."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(change, dict):
        return None
    if change.get("field") != "message_template_status_update":
        return None
    value = change.get("value")
    if not isinstance(value, dict):
        return None
    event = value.get("event")
    if not isinstance(event, str) or not event:
        return None
    return {
        "waba_id": str(entry.get("id") or "") or None,
        "event": event,
        "message_template_id": (
            str(value["message_template_id"])
            if value.get("message_template_id") is not None
            else None
        ),
        "message_template_name": (
            value.get("message_template_name")
            if isinstance(value.get("message_template_name"), str)
            else None
        ),
        "message_template_language": (
            value.get("message_template_language")
            if isinstance(value.get("message_template_language"), str)
            else None
        ),
        "reason": (
            value.get("reason")
            if isinstance(value.get("reason"), str)
            else None
        ),
    }


def _verify_whatsapp_signature(
    *,
    raw: bytes,
    signature_header: str | None,
    config: Any,
    platform_secret: str,
) -> None:
    """Verify the ``X-Hub-Signature-256`` header. Raises 403 on
    mismatch and 500 when neither the env-side platform secret nor the
    per-org ``app_secret_enc`` is configured.

    Hoisted out of the messages branch so the template-status branch
    can reuse it; the messages branch still has the same inline check
    for tests-shaped fidelity. ``config`` is a ``WhatsAppAccountConfig``
    but typed loose to avoid an import cycle between the conversations
    router and the integrations package."""
    from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter
    from src.app.core.integrations.crypto import decrypt

    app_secret = platform_secret
    if not app_secret:
        if not config.app_secret_enc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "WhatsApp signature secret is not configured for "
                    "this org and no platform-level WHATSAPP_APP_SECRET "
                    "is set."
                ),
            )
        app_secret = decrypt(config.app_secret_enc)
    adapter = WhatsAppAdapter(
        phone_id=config.phone_id,
        token="",
        app_secret=app_secret,
        verify_token=config.verify_token,
        api_version=config.api_version,
    )
    if not adapter.verify_signature(raw, signature_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid webhook signature",
        )
