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

import json
import uuid
from datetime import UTC
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, PlainTextResponse
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
from src.app.core.conversations.notes_service import post_note
from src.app.core.conversations.registry import (
    ChannelNotRegistered,
    resolve,
)
from src.app.core.conversations.schemas import (
    AssignTagRequest,
    AttachmentType,
    ConversationAttributionOut,
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationOut,
    ConversationPatch,
    EmailReplyPayload,
    MessageOut,
    MessageSendPayload,
    NoteCreate,
    ReactionRequest,
    SendTemplatePayload,
    TagCreate,
    TagOut,
    TagUpdate,
)
from src.app.core.conversations.service import (
    bulk_last_message_bodies,
    ensure_can_write_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    mark_conversation_read,
    mark_conversation_unread,
    patch_conversation,
    pause_ai,
    react_to_message,
    receive_webhook,
    resume_ai,
    send_email_reply,
    send_outbound,
    send_template_message,
    start_conversation,
)
from src.app.core.permissions.service import role_has_permission
from src.app.core.conversations.tags_service import (
    assign_tag,
    bulk_tags_for_conversations,
    create_tag,
    delete_tag,
    list_tags,
    list_tags_for_conversation,
    unassign_tag,
    update_tag,
)
from src.app.core.conversations.whatsapp_session import (
    compute_session_state,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/conversations", tags=["Conversations"])

# mailgun-inbound Step 5: a SEPARATE router mounted alongside the
# conversations router so the URL surface is ``/messages/{id}/...``
# rather than ``/conversations/messages/{id}/...``. Composition happens
# in main.py — this router is exported and included at prefix
# ``/api/v1`` (like the ownership_router pattern).
message_attachments_router = APIRouter(
    prefix="/messages", tags=["Message Attachments"]
)

_ATTACHMENT_KEY_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,255}$")


@message_attachments_router.get(
    "/{message_id}/attachments/{safe_key}",
    response_class=FileResponse,
)
async def download_message_attachment(
    message_id: uuid.UUID,
    safe_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.read")),
) -> FileResponse:
    """Serve an inbound-email attachment from local disk.

    Auth: JWT (via ``conversations.read``) + explicit ``org_id`` check
    against the message row + ``safe_key`` regex guard against path
    traversal. Content-Disposition ALWAYS ``attachment`` (never
    ``inline``) regardless of the sniffed content type — PDFs, images,
    HTML would all render inline in the browser and become XSS /
    exploit vectors on our origin. Force-download shifts the risk to
    the user's local viewer (Attacker H3 fix).

    404 on cross-org access, missing key, or missing file on disk —
    never 403 (no signal of existence)."""
    from pathlib import Path as _Path

    from src.app.core.conversations import data_access as _da

    if not _ATTACHMENT_KEY_RE.match(safe_key):
        raise HTTPException(status_code=400, detail="invalid attachment key")

    msg = await _da.get_message_by_id(db, message_id)
    if msg is None or msg.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="attachment not found")

    # The Message row must list this key in its attachments JSONB —
    # prevents an attacker from downloading a sibling file by name
    # even after guessing the message id.
    entries = msg.attachments or []
    matched = next(
        (e for e in entries if e.get("storage_key") == safe_key), None
    )
    if matched is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    storage_root = _Path(
        __import__("os").getenv("STORAGE_ROOT", "./storage")
    )
    file_path = (
        storage_root / str(msg.org_id) / "messages" / str(msg.id) / safe_key
    )
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="attachment not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_key}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _require_conversation_write_access(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> uuid.UUID:
    """Reused by every write endpoint that operates on a specific
    conversation: reply, react, tag, mark-read, close, take-over-AI.

    Enforces the new ownership model — a chat assigned to another
    user is view-only for anyone who isn't the assignee or an
    Owner/Admin (``conversations.assign_others``). Unassigned chats
    stay open to any writer so the "any employee can jump in" flow
    still works.

    Returns the resolved conversation id so the endpoint can pass it
    down to the service without a second lookup (the service function
    still `get_conversation`s internally — the double-fetch cost is
    negligible next to the network round-trip and keeps the service
    contract clean).
    """
    conv = await get_conversation(db, conversation_id)
    await ensure_can_write_conversation(
        db,
        conv=conv,
        caller_user_id=user.legacy_uuid,
        caller_role_id=user.role_id,
    )
    return conv.id


@router.get("", response_model=ConversationListResponse)
async def list_endpoint(
    channel: ConversationChannel | None = Query(default=None),
    status_: ConversationStatus | None = Query(default=None, alias="status"),
    # Widened to `str` so the sentinel value `'unassigned'` can pass
    # through (matches the leads / contacts convention). The service
    # parses the value: a UUID maps to equality; `'unassigned'` maps
    # to `IS NULL`; anything else is rejected with a 422-style error.
    assigned_to: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=255),
    # Step 14 — OR-semantic tag filter. Repeat the query param to
    # match multiple tags: ?tag_ids=uuid1&tag_ids=uuid2.
    tag_ids: list[uuid.UUID] | None = Query(default=None),
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
        tag_ids=tag_ids,
        page=page,
        size=size,
    )
    # Bulk-fetch tags + last-message previews for the rows we're about
    # to return so the chip row + preview line in the list view don't
    # N+1 the inbox render.
    conv_ids = [r.id for r in rows]
    tags_by_conv = await bulk_tags_for_conversations(db, conv_ids)
    preview_by_conv = await bulk_last_message_bodies(db, conv_ids)
    items = []
    for r in rows:
        out = ConversationOut.model_validate(r)
        out.tags = tags_by_conv.get(r.id, [])
        out.last_message_body = preview_by_conv.get(r.id)
        items.append(out)
    return ConversationListResponse(items=items, total=total, page=page, size=size)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.write")),
) -> ConversationOut:
    """Start a new outbound conversation from the inbox's *New*
    button. The service resolves the picked contact's phone / email
    based on channel and reuses the existing find-or-create path so
    the operator lands in the existing thread if one is already open."""

    conv = await start_conversation(
        db,
        channel=payload.channel,
        contact_id=payload.contact_id,
    )
    return ConversationOut.model_validate(conv)


# --- Tags (whatsapp-platform-upgrade Step 14) -----------------------------
# NOTE: These MUST be declared BEFORE ``GET /{conversation_id}`` and the
# other ``/{conversation_id}`` greedy routes. FastAPI matches routes in
# registration order — if ``/{conversation_id}`` comes first, a request
# for ``/tags`` gets caught by it and 422's trying to parse ``"tags"`` as
# a UUID. Same pattern as any static-path-vs-{id} collision; kept close
# to the top of the router so future edits don't accidentally re-break
# it.


@router.get("/tags", response_model=list[TagOut])
async def list_tags_endpoint(
    search: str | None = Query(default=None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> list[TagOut]:
    """Return every tag in the active org with its assignment count.
    Read-gated on `conversations.read` so junior staff can render the
    chip palette + filter chip without needing the manage key."""
    rows = await list_tags(db, search=search)
    return [TagOut.model_validate(r) for r in rows]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag_endpoint(
    payload: TagCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.conversations.manage")),
) -> TagOut:
    tag = await create_tag(
        db,
        actor_id=user.legacy_uuid,
        org_id=user.org_id,
        name=payload.name,
        color=payload.color,
    )
    return TagOut.model_validate(tag)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag_endpoint(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.conversations.manage")),
) -> TagOut:
    tag = await update_tag(
        db,
        actor_id=user.legacy_uuid,
        tag_id=tag_id,
        name=payload.name,
        color=payload.color,
    )
    return TagOut.model_validate(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_endpoint(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.conversations.manage")),
) -> Response:
    await delete_tag(db, actor_id=user.legacy_uuid, tag_id=tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Thread message page size — 50 is small enough to render fast on
# cold open even with big media, large enough to cover an ordinary
# WhatsApp session so most opens never need a "Load older" click.
_THREAD_MESSAGES_PAGE_SIZE = 50


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_detail_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> ConversationDetail:
    """Thread detail — returns the **most recent** page of messages,
    not the full history.

    Long-running WhatsApp threads (hundreds or thousands of messages
    over months) used to fetch every row on every open. The paginated
    read caps first-paint at 50 messages; the SPA hits
    ``/{conversation_id}/messages?before_id=…`` when the operator
    scrolls up to load older pages.
    """
    conv = await get_conversation(db, conversation_id)
    msgs = await list_messages(db, conversation_id, limit=_THREAD_MESSAGES_PAGE_SIZE)
    conv_out = ConversationOut.model_validate(conv)
    conv_out.tags = await list_tags_for_conversation(db, conversation_id)
    # Step 15 — attach WhatsApp 24-hour session state only for
    # whatsapp conversations. Other channels (SMS / Email / web)
    # have no session-window concept; the banner stays hidden.
    session_state = None
    if conv.channel == ConversationChannel.whatsapp:
        session_state = compute_session_state(conv.last_customer_message_at)
    return ConversationDetail(
        conversation=conv_out,
        messages=[MessageOut.model_validate(m) for m in msgs],
        whatsapp_session_state=session_state,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageOut],
    summary="Fetch an older page of messages on this conversation (infinite-scroll-up).",
)
async def list_older_messages_endpoint(
    conversation_id: uuid.UUID,
    before_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> list[MessageOut]:
    """Return the page of messages **older than** ``before_id`` on this
    conversation, oldest-first (append to the top of the rendered
    thread). Caller passes the id of the currently-oldest visible row
    as the ``before_id`` anchor. Empty list means there's nothing
    older — the SPA hides the "Load older" button.

    ``limit`` clamped to ``[1, 200]`` — same shape the inbox list uses.
    Ties on ``created_at`` are broken by ``id`` so a webhook batch that
    landed two messages in the same second doesn't get returned twice.
    """
    capped_limit = max(1, min(int(limit), 200))
    # Existence check so a bad ``before_id`` returns 404 rather than
    # silently walking the whole thread as if no anchor was supplied.
    await get_conversation(db, conversation_id)
    msgs = await list_messages(db, conversation_id, limit=capped_limit, before_id=before_id)
    return [MessageOut.model_validate(m) for m in msgs]


@router.post(
    "/{conversation_id}/tags",
    response_model=list[dict[str, Any]],
)
async def assign_tag_endpoint(
    conversation_id: uuid.UUID,
    payload: AssignTagRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> list[dict[str, Any]]:
    """Attach an existing tag to a conversation. Idempotent — a
    re-assignment is a no-op. Returns the post-assignment tag list
    so the SPA can swap chips without re-fetching."""
    return await assign_tag(
        db,
        actor_id=user.legacy_uuid,
        org_id=user.org_id,
        conversation_id=conversation_id,
        tag_id=payload.tag_id,
    )


@router.delete(
    "/{conversation_id}/tags/{tag_id}",
    response_model=list[dict[str, Any]],
)
async def unassign_tag_endpoint(
    conversation_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> list[dict[str, Any]]:
    return await unassign_tag(
        db,
        actor_id=user.legacy_uuid,
        conversation_id=conversation_id,
        tag_id=tag_id,
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
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> MessageOut:
    # Must carry at least one of the three payloads — the schema relaxed
    # `text` to optional to allow interactive-only sends, so re-check at
    # the boundary instead of with a Pydantic root validator (keeps the
    # error message friendlier).
    if not payload.text and not payload.attachments and payload.interactive is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Message must include text, an attachment, or an interactive payload."),
        )
    interactive_dict = (
        payload.interactive.model_dump(mode="json") if payload.interactive is not None else None
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
            send_from_phone_id=payload.send_from_phone_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/messages/template",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_template_message_endpoint(
    conversation_id: uuid.UUID,
    payload: SendTemplatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> MessageOut:
    """Send an approved WhatsApp template message inside an existing
    conversation. Powers the inbox composer's inline template picker
    when the 24-hour session window has expired — Meta only accepts
    approved templates outside the window.

    Error translation (all messages user-facing — surfaced verbatim
    on the SPA's error banner):

    * ``ValueError`` → 400 with the raised message. Covers wrong
      channel, blocklist hit, template not approved, variable count
      / key mismatch.
    * ``WhatsAppNotConnected`` → 409 — org has no active WhatsApp
      integration; prompt to reconnect in Settings → Integrations.
    * ``WhatsAppRateLimited`` → 429 with ``Retry-After`` set from
      Meta so the SPA can back off cleanly.
    * ``WhatsAppSendError`` → 502 — Meta refused the send (bad
      template state, phone unreachable, invalid variable value).
      Message carries Meta's raw reason for debugging.
    """
    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppRateLimited,
        WhatsAppSendError,
    )

    try:
        msg = await send_template_message(
            db,
            conversation_id=conversation_id,
            user_id=user.legacy_uuid,
            template_id=payload.template_id,
            variables=payload.variables,
            send_from_phone_id=payload.send_from_phone_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WhatsAppNotConnected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "WhatsApp is not connected for this organisation. "
                "Reconnect it in Settings → Integrations, then try again."
            ),
        ) from exc
    except WhatsAppRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"WhatsApp rate limit hit — try again in "
                f"{exc.retry_after_seconds}s. Meta throttles bursts to "
                "protect the sender's number."
            ),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except WhatsAppSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(f"Meta refused this template send. Details: {str(exc)[:400]}"),
        ) from exc
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/email-reply",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def email_reply_endpoint(
    conversation_id: uuid.UUID,
    payload: EmailReplyPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> MessageOut:
    """Reply to an email conversation from the unified inbox
    (Intercom-style). The generic ``/messages`` send guards email
    with a 400 because it needs subject + sender-account context this
    body carries. Defaults so the composer's body-only send works:
      * ``account_id`` — first ``live`` mailbox the sender has connected.
      * ``subject`` — neutral ``Re: (no subject)``; caller may override.
      * threading — the newest inbound message on the thread is
        auto-picked as ``in_reply_to_message_id`` so Gmail / Outlook
        collapse the reply into the customer's original chain.
    """
    msg = await send_email_reply(
        db,
        conversation_id=conversation_id,
        user_id=user.legacy_uuid,
        body_text=payload.body_text,
        body_html=payload.body_html,
        subject=payload.subject,
        account_id=payload.account_id,
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
    _access: uuid.UUID = Depends(_require_conversation_write_access),
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
    _access: uuid.UUID = Depends(_require_conversation_write_access),
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    caption: str | None = Form(default=None, max_length=MAX_CAPTION_LENGTH),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
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
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message) from exc

    try:
        bundle = await resolve_whatsapp_adapter(db)
    except WhatsAppNotConnected as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

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
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message) from exc

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
    user: User = Depends(require_permissions("conversations.write")),
) -> ConversationOut:
    conv = await patch_conversation(
        db,
        conversation_id=conversation_id,
        payload=payload,
        caller_user_id=user.legacy_uuid,
        caller_role_id=user.role_id,
    )
    return ConversationOut.model_validate(conv)


# --- AI takeover (omnichannel Step 3) ------------------------------------


@router.post(
    "/{conversation_id}/pause-ai",
    response_model=ConversationOut,
    summary="Human takes over — pause AI on this conversation.",
)
async def pause_ai_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> ConversationOut:
    """First-come-first-serve takeover. Body-less POST — the CAS is
    idempotent per row: the first caller wins with 200; concurrent
    callers get 409 ``already_taken_over`` naming the winner so the
    UI can render *"Alice just took this over."* and refresh the
    inbox. A system marker message is inserted into the thread to
    record the handoff for the transcript."""
    conv = await pause_ai(
        db,
        conversation_id=conversation_id,
        actor_user_id=user.legacy_uuid,
    )
    return ConversationOut.model_validate(conv)


@router.post(
    "/{conversation_id}/resume-ai",
    response_model=ConversationOut,
    summary="Hand this conversation back to the AI.",
)
async def resume_ai_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> ConversationOut:
    """Symmetric of :func:`pause_ai_endpoint`. Only the current holder
    OR an admin (``settings.conversations.manage``) can resume; other
    callers get 403 ``not_holder``. Calling on an already-unpaused
    conversation returns 409 ``not_paused``."""
    caller_is_admin = await role_has_permission(db, user.role_id, "settings.conversations.manage")
    conv = await resume_ai(
        db,
        conversation_id=conversation_id,
        actor_user_id=user.legacy_uuid,
        caller_is_admin=caller_is_admin,
    )
    return ConversationOut.model_validate(conv)


@router.post(
    "/{conversation_id}/mark-read",
    response_model=ConversationOut,
    summary="Zero the unread badge on this conversation.",
)
async def mark_read_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> ConversationOut:
    """Zero ``unread_count`` on the conversation. Idempotent — hitting
    this on an already-read conversation is a no-op (no audit spam).

    Was a Phase-1 UX gap: inbound webhooks bumped the counter but there
    was no user-facing path to clear it. The SPA calls this on thread
    open and from a right-click "Mark as read" menu on the list row.
    """
    conv = await mark_conversation_read(db, conversation_id=conversation_id)
    return ConversationOut.model_validate(conv)


@router.post(
    "/{conversation_id}/mark-unread",
    response_model=ConversationOut,
    summary='Flip the unread badge back on ("come back to this later").',
)
async def mark_unread_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.write")),
    _access: uuid.UUID = Depends(_require_conversation_write_access),
) -> ConversationOut:
    """Set ``unread_count = 1`` if it's currently 0. Matches Gmail /
    Slack / Intercom — the badge signals "something to see" without
    lying about how many messages are actually unseen. Idempotent when
    the row is already unread.
    """
    conv = await mark_conversation_unread(db, conversation_id=conversation_id)
    return ConversationOut.model_validate(conv)


@router.get(
    "/{conversation_id}/attribution",
    response_model=ConversationAttributionOut,
    summary="Click-to-WhatsApp ad attribution for a conversation (Step 24).",
)
async def get_conversation_attribution_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> ConversationAttributionOut:
    """Return the captured referral metadata + a Meta Ads Manager
    deeplink (when the ad was resolved on capture). Conversations
    without attribution return a row with ``source=None`` so the
    SPA can render "Organic" without a 404 branch."""
    from src.app.core.integrations.meta.ads_lookup import (
        deeplink_for_ad,
    )

    conv = await get_conversation(db, conversation_id)
    payload = conv.acquisition_referral_payload or {}
    resolved = (
        payload.get("_resolved") if isinstance(payload.get("_resolved"), dict) else None
    ) or {}
    deeplink = deeplink_for_ad(resolved) if resolved else None
    return ConversationAttributionOut(
        conversation_id=conv.id,
        source=conv.acquisition_source,
        campaign_id=conv.acquisition_campaign_id,
        campaign_name=resolved.get("campaign_name"),
        ad_id=conv.acquisition_ad_id,
        ad_name=resolved.get("ad_name"),
        landing_url=conv.acquisition_landing_url,
        deeplink=deeplink,
        payload=payload,
    )


@router.get(
    "/{conversation_id}/export.csv",
    summary="Download conversation transcript as CSV (Step 23 / DPDP).",
)
async def export_conversation_csv_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> Response:
    """CSV transcript excluding internal notes (Step 13). Anyone
    with `conversations.read` can export their own conversations —
    DPDP right-to-access is the rationale; the audit log on the
    server records the download."""
    from src.app.core.conversations.export import export_conversation_csv

    blob, filename, _conv, _msgs = await export_conversation_csv(
        db, conversation_id=conversation_id
    )
    return Response(
        content=blob,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/{conversation_id}/export.pdf",
    summary="Download conversation transcript as PDF (Step 23 / DPDP).",
)
async def export_conversation_pdf_endpoint(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("conversations.read")),
) -> Response:
    """PDF transcript. Same data as CSV — rendered for human
    review (legal disclosure / customer-service handoff). Internal
    notes excluded."""
    from src.app.core.conversations.export import export_conversation_pdf

    try:
        blob, filename = await export_conversation_pdf(db, conversation_id=conversation_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.patch("/{conversation_id}/ai-handling", response_model=ConversationOut)
async def patch_ai_handling_endpoint(
    conversation_id: uuid.UUID,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("conversations.write")),
) -> ConversationOut:
    """Dedicated toggle for the AI-handling flag
    (whatsapp-platform-upgrade Step 19).

    Equivalent to ``PATCH /{id}`` with `{ai_handling: bool}`, but
    surfaces a friendlier 422 when the body is malformed + audits
    under a dedicated event name so analytics can count toggles
    separately from generic triage edits."""
    raw = payload.get("ai_handling")
    if not isinstance(raw, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`ai_handling` must be true or false.",
        )
    conv = await patch_conversation(
        db,
        conversation_id=conversation_id,
        payload=ConversationPatch(ai_handling=raw),
        caller_user_id=user.legacy_uuid,
        caller_role_id=user.role_id,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not hasattr(adapter, "verify_subscription"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"channel '{channel.value}' has no subscription handshake",
        )
    if not adapter.verify_subscription(mode, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verify failed")
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
        ) from exc

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
        bundle = await find_org_by_waba_id(db, waba_id=quality_event["waba_id"])
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(f"no WhatsApp integration found for waba_id={quality_event['waba_id']}"),
            )
        integration, config = bundle
        _verify_whatsapp_signature(
            raw=raw,
            signature_header=request.headers.get("x-hub-signature-256"),
            config=config,
            platform_secret=WHATSAPP_APP_SECRET,
        )
        set_context(RequestContext(org_id=integration.org_id, user_id=None))
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
        bundle = await find_org_by_waba_id(db, waba_id=template_event["waba_id"])
        if bundle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(f"no WhatsApp integration found for waba_id={template_event['waba_id']}"),
            )
        integration, config = bundle
        _verify_whatsapp_signature(
            raw=raw,
            signature_header=request.headers.get("x-hub-signature-256"),
            config=config,
            platform_secret=WHATSAPP_APP_SECRET,
        )
        set_context(RequestContext(org_id=integration.org_id, user_id=None))
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
        from src.app.core.conversations.service import apply_channel_status_to_message

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
            # Also reflect the status onto the parallel Message row +
            # publish workflow events (``whatsapp.message_read``).
            # apply_meta_status covers CampaignMessage; this covers
            # the general Message table used by the inbox. Both are
            # keyed by the same Meta wamid, so a single status event
            # updates both.
            await apply_channel_status_to_message(
                db,
                channel_message_id=event.channel_message_id,
                meta_status=event.status,
                timestamp=event.timestamp,
            )
        return {"updated": updated}

    # whatsapp-platform-upgrade Step 23 — early block-list drop.
    # Runs BEFORE `receive_webhook` so a blocked number never creates
    # a conversation row, never trips auto-reply / AI / assignment,
    # and never writes to the inbox. We return 202 so Meta doesn't
    # retry — silent drop is the spec'd behaviour.
    from src.app.core.conversations.adapters.whatsapp import (
        parse_inbound_phone,
    )
    from src.app.core.integrations.whatsapp.block_list import is_blocked

    blocked_phone = parse_inbound_phone(payload)
    if blocked_phone:
        hit = await is_blocked(db, org_id=integration.org_id, phone=blocked_phone)
        if hit is not None:
            from src.app.core import audit

            await audit.log(
                "whatsapp.block_list.inbound_dropped",
                entity_type="whatsapp_block",
                entity_id=hit.id,
                after={
                    "phone_number": hit.phone_number,
                    "reason": hit.reason,
                },
            )
            return {"blocked": True, "reason": hit.reason}

    try:
        # Step 27a — pass the resolved phone_id through so
        # `_find_or_create_conversation` can stamp it on new
        # conversations. ``config.phone_id`` is the Meta-side
        # phone-number-id that the webhook authenticator already
        # resolved this inbound to.
        # WhatsApp adapters are constructed per-org (not registered
        # in the global channel registry), so parse here with the
        # already-built ``adapter`` and pass through as ``pre_parsed``
        # to skip ``resolve(channel)`` inside ``receive_webhook``.
        parsed_inbound = adapter.parse_webhook(payload)
        msg = await receive_webhook(
            db,
            channel=ConversationChannel.whatsapp,
            payload=payload,
            received_via_phone_id=config.phone_id,
            pre_parsed=parsed_inbound,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    from datetime import datetime

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
    phone_id = str(raw_phone) if isinstance(raw_phone, (str, int)) else ""
    if not phone_id:
        return None
    occurred_at: datetime | None = None
    raw_ts = value.get("timestamp") or entry.get("time")
    if isinstance(raw_ts, (int, float)):
        try:
            occurred_at = datetime.fromtimestamp(int(raw_ts), tz=UTC)
        except (TypeError, ValueError):
            occurred_at = None
    return {
        "waba_id": str(entry.get("id") or "") or None,
        "phone_id": phone_id,
        "event": event,
        "current_limit": (
            value.get("current_limit") if isinstance(value.get("current_limit"), str) else None
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
        "reason": (value.get("reason") if isinstance(value.get("reason"), str) else None),
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
