"""Internal notes service (whatsapp-platform-upgrade Step 13).

Single entry point — :func:`post_note` — that writes an
``is_internal=true`` `Message` row to the conversation AND fans out
one in-app notification per ``@``-mention.

Key invariants:

  * **Never** call any channel adapter — notes don't reach the
    customer. The standard ``send_outbound`` path is bypassed
    entirely; we insert the row directly.
  * Mentions are validated against active org membership before
    insert. Unknown ids fail the request with 400.
  * Mention notifications use the existing ``notifications.notify``
    helper — same in-app + WS-push path as conversation messages.
  * Cap on mentions is enforced by the Pydantic schema (max 5);
    this layer trusts the caller.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations import data_access as _da
from src.app.core.conversations.models import (
    Message,
    MessageDirection,
)
from src.app.core.notifications.service import notify

logger = logging.getLogger(__name__)


async def _validate_mentions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    mentioned_user_ids: list[uuid.UUID],
) -> list[tuple[uuid.UUID, str]]:
    """Confirm every mentioned id is an active member of the active
    org. Returns ``[(user_uuid, display_name), …]`` so the
    notification body can include the sender + recipient names.

    Unknown ids surface as a 400 — the operator's UI should only
    have shown valid pickable users, so a stale id is an integrity
    bug worth telling them about.
    """
    if not mentioned_user_ids:
        return []

    rows = await _da.list_active_members_with_names(
        session, org_id=org_id, user_uuids=mentioned_user_ids
    )

    found = {
        row[0]: f"{row[1] or ''} {row[2] or ''}".strip() or "User"
        for row in rows
    }
    missing = [uid for uid in mentioned_user_ids if uid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "One or more mentioned users are not active members "
                "of this organization."
            ),
        )
    return [(uid, found[uid]) for uid in mentioned_user_ids]


async def post_note(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    author_id: uuid.UUID,
    text: str,
    mentioned_user_ids: list[uuid.UUID],
) -> Message:
    """Persist an internal note + dispatch mention notifications.

    Returns the new `Message` row so the frontend can swap its
    optimistic placeholder for the real id + timestamps. Does NOT
    touch any channel adapter — notes are an in-CRM-only surface."""
    conv = await _da.get_conversation_by_id(session, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    validated = await _validate_mentions(
        session,
        org_id=conv.org_id,
        mentioned_user_ids=mentioned_user_ids,
    )

    now = datetime.now(timezone.utc)
    note = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.out,
        sender_user_id=author_id,
        text=text,
        attachments=[],
        is_internal=True,
        mentioned_user_ids=list(mentioned_user_ids),
        # Internal notes share the message row shape but skip every
        # channel-side field. No `channel_message_id`, no `sent_at` —
        # the row's `created_at` is the only meaningful timestamp.
        sent_at=now,
        payload={"internal_note": True},
    )
    _da.insert_message(session, note)
    # Notes don't bump unread_count (the inbox-list badge tracks
    # customer-driven attention, not internal chatter), but DO move
    # the conversation to the top so the author's teammates see it
    # surface immediately.
    conv.last_message_at = now
    await session.commit()
    await session.refresh(note)
    await session.refresh(conv)

    await audit.log(
        "conversations.internal_note_posted",
        entity_type="conversation",
        entity_id=conv.id,
        user_id=author_id,
        after={
            "message_id": str(note.id),
            "mention_count": len(validated),
        },
    )

    # Dispatch mention notifications. `notify()` is non-raising —
    # failures get logged but don't roll the note back.
    preview = text[:160]
    for user_uuid, _name in validated:
        if user_uuid == author_id:
            # No notification for self-mentions — the author is
            # already aware they typed their own name.
            continue
        await notify(
            org_id=conv.org_id,
            user_id=user_uuid,
            type="conversation.mention",
            title="You were mentioned in a conversation",
            body=preview,
            payload={
                "conversation_id": str(conv.id),
                "message_id": str(note.id),
                "channel": conv.channel.value,
            },
        )

    return note


__all__ = ["post_note"]
