"""Service layer for the conversations engine.

Five concerns:

1. `list_conversations` — paginated + filter-aware inbox query
   (`channel`, `status`, `assigned_to_id`, `q` ILIKE on `external_id`).
   Ordered by `last_message_at desc nulls last`.
2. `get_conversation_detail` — one conversation + its messages,
   newest first per the inbox UX.
3. `send_outbound` — resolve the channel adapter, call `send()`,
   persist a `direction='out'` row, bump `last_message_at`. On the
   *first* outbound for a conversation tied to a contact, log a
   `whatsapp` activity (the only chat-style ActivityType today) so the
   contact timeline picks it up.
4. `receive_webhook` — channel-agnostic intake. Calls the adapter's
   `parse_webhook`, finds/creates the matching `Conversation`,
   persists a `direction='in'` row, bumps `unread_count` +
   `last_message_at`, fans out a notification to the assignee (if any)
   via the 2.15 service.
5. `patch_conversation` — narrow PATCH for the three triage fields.

All writes route through the caller's `AsyncSession` so the request
transaction stays in charge. Activity / notification fan-outs use
their respective `log` / `notify` helpers, both of which are
non-raising.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import InboundMessage
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.conversations.adapters.whatsapp import (
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.registry import resolve
from src.app.core.conversations.schemas import ConversationPatch
from src.app.core.notifications.service import notify
from src.app.shared.db.queries import get_or_404


# Channels whose `external_id` is a phone number; the webhook intake
# tries to resolve / auto-create a contact for these so the inbox can
# show a name instead of the raw phone string.
_PHONE_CHANNELS = {ConversationChannel.whatsapp, ConversationChannel.sms}


# --- reads -----------------------------------------------------------------


async def list_conversations(
    session: AsyncSession,
    *,
    channel: Optional[ConversationChannel] = None,
    status_filter: Optional[ConversationStatus] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    q: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Conversation], int]:
    filters: list[Any] = []
    if channel is not None:
        filters.append(Conversation.channel == channel)
    if status_filter is not None:
        filters.append(Conversation.status == status_filter)
    if assigned_to_id is not None:
        filters.append(Conversation.assigned_to_id == assigned_to_id)
    if q:
        filters.append(Conversation.external_id.ilike(f"%{q}%"))

    where = and_(*filters) if filters else None
    base = select(Conversation)
    if where is not None:
        base = base.where(where)
    base = base.order_by(
        Conversation.last_message_at.desc().nullslast(),
        Conversation.created_at.desc(),
    )

    total_stmt = select(func.count()).select_from(Conversation)
    if where is not None:
        total_stmt = total_stmt.where(where)
    total = (await session.execute(total_stmt)).scalar_one()

    offset = (page - 1) * size
    rows = (
        (await session.execute(base.offset(offset).limit(size)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation:
    return await get_or_404(session, Conversation, conversation_id, entity="conversation")


async def list_messages(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# --- writes ----------------------------------------------------------------


async def send_outbound(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    text_body: str,
    attachments: list[dict[str, Any]],
) -> Message:
    conv = await get_conversation(session, conversation_id)
    # WhatsApp goes through the per-org resolver (Step 3.5.3) — it
    # loads the active tenant's encrypted token from the integrations
    # table and instantiates an adapter with those credentials. Other
    # channels stay on the registry's zero-arg factory.
    if conv.channel == ConversationChannel.whatsapp:
        adapter = await resolve_whatsapp_adapter(session)
    else:
        adapter = resolve(conv.channel)

    is_first_outbound = await _is_first_outbound(session, conversation_id)

    ref = await adapter.send(
        org_id=conv.org_id,
        external_id=conv.external_id,
        text=text_body,
        attachments=attachments,
    )
    now = datetime.now(timezone.utc)
    sent_at = ref.sent_at or now

    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.out,
        sender_user_id=user_id,
        text=text_body,
        attachments=attachments,
        channel_message_id=ref.channel_message_id,
        payload={"adapter_ref": ref.channel_message_id},
        sent_at=sent_at,
    )
    session.add(msg)
    conv.last_message_at = sent_at
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conv)

    await audit.log(
        "conversations.message_sent",
        entity_type="conversation",
        entity_id=conv.id,
        after={
            "channel": conv.channel.value,
            "external_id": conv.external_id,
            "message_id": str(msg.id),
        },
    )
    if is_first_outbound and conv.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=conv.contact_id,
            type=ActivityType.whatsapp
            if conv.channel == ConversationChannel.whatsapp
            else ActivityType.note,
            payload={
                "channel": conv.channel.value,
                "preview": text_body[:120],
                "conversation_id": str(conv.id),
            },
            user_id=user_id,
            org_id=conv.org_id,
        )
    return msg


async def receive_webhook(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    payload: dict[str, Any],
) -> Message:
    adapter = resolve(channel)
    parsed: InboundMessage = adapter.parse_webhook(payload)

    conv = await _find_or_create_conversation(
        session, channel=channel, external_id=parsed.external_id
    )
    sent_at = parsed.sent_at or datetime.now(timezone.utc)

    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.in_,
        text=parsed.text,
        attachments=parsed.attachments,
        channel_message_id=parsed.channel_message_id,
        payload=parsed.raw,
        sent_at=sent_at,
    )
    session.add(msg)
    conv.last_message_at = sent_at
    conv.unread_count = (conv.unread_count or 0) + 1
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conv)

    if conv.assigned_to_id is not None:
        await notify(
            org_id=conv.org_id,
            user_id=conv.assigned_to_id,
            type="conversation.message",
            title=f"New message on {conv.channel.value}",
            body=(parsed.text or "")[:160] or None,
            payload={
                "conversation_id": str(conv.id),
                "channel": conv.channel.value,
            },
        )
    return msg


async def patch_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    payload: ConversationPatch,
) -> Conversation:
    conv = await get_conversation(session, conversation_id)
    before = _snapshot(conv)
    changed = False
    if payload.assigned_to_id is not None:
        conv.assigned_to_id = payload.assigned_to_id
        changed = True
    if payload.status is not None:
        conv.status = payload.status
        changed = True
    if payload.ai_handling is not None:
        conv.ai_handling = payload.ai_handling
        changed = True
    if changed:
        await session.commit()
        await session.refresh(conv)
        await audit.log(
            "conversations.patched",
            entity_type="conversation",
            entity_id=conv.id,
            before=before,
            after=_snapshot(conv),
        )
    return conv


# --- helpers ---------------------------------------------------------------


async def _is_first_outbound(
    session: AsyncSession, conversation_id: uuid.UUID
) -> bool:
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.out)
    )
    return ((await session.execute(stmt)).scalar_one() or 0) == 0


async def _find_or_create_conversation(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    external_id: str,
) -> Conversation:
    existing = (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == channel)
            .where(Conversation.external_id == external_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # New conversation — `org_id` comes from `RequestContext` via the
    # TenantScoped mixin (webhook intake sets it on the way in).
    from src.app.shared.context import get_context

    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook has no tenant context",
        )

    contact_id = None
    if channel in _PHONE_CHANNELS:
        contact_id = await _resolve_or_create_contact_by_phone(
            session, org_id=ctx.org_id, phone=external_id
        )

    conv = Conversation(
        org_id=ctx.org_id,
        channel=channel,
        external_id=external_id,
        contact_id=contact_id,
        status=ConversationStatus.open,
    )
    session.add(conv)
    await session.flush()
    return conv


async def _resolve_or_create_contact_by_phone(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
) -> uuid.UUID | None:
    """Look up a contact by phone in this org. If none exists, create
    one with `full_name = phone` as a placeholder so the inbox has a
    row to render. Returns the resolved/created contact id, or None if
    the phone string is empty."""
    if not phone:
        return None
    existing = (
        await session.execute(
            select(Contact).where(Contact.phone == phone)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    contact = Contact(
        org_id=org_id,
        full_name=phone,
        phone=phone,
        source="whatsapp",
    )
    session.add(contact)
    await session.flush()
    return contact.id


def _snapshot(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "channel": c.channel.value,
        "external_id": c.external_id,
        "contact_id": str(c.contact_id) if c.contact_id else None,
        "assigned_to_id": str(c.assigned_to_id) if c.assigned_to_id else None,
        "status": c.status.value,
        "ai_handling": c.ai_handling,
    }


__all__ = [
    "get_conversation",
    "list_conversations",
    "list_messages",
    "patch_conversation",
    "receive_webhook",
    "send_outbound",
]
