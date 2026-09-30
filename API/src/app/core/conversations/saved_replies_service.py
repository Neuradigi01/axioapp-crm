"""Saved replies ("canned responses") for the conversations composer.

Owns CRUD for ``tbl_conversation_saved_replies``. Permission split:

  * List → ``conversations.read`` (router gate).
  * Create → ``conversations.write`` (router gate) — anyone who can
    reply can save a reply for the team.
  * Edit / Delete → the reply's author, or a holder of
    ``settings.conversations.manage`` (checked here).

Shortcut uniqueness (case-insensitive, per org) is enforced by the
``uq_conv_saved_replies_org_shortcut`` partial index; the IntegrityError
is translated to a 409.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations import data_access as _da
from src.app.core.conversations.models import ConversationSavedReply
from src.app.core.conversations.schemas import SavedReplyCreate, SavedReplyUpdate
from src.app.core.permissions.service import role_has_permission

_MANAGE_KEY = "settings.conversations.manage"


def _snapshot(reply: ConversationSavedReply) -> dict[str, str | None]:
    return {"title": reply.title, "shortcut": reply.shortcut}


async def list_saved_replies(
    session: AsyncSession, *, search: str | None = None
) -> list[ConversationSavedReply]:
    return await _da.list_saved_replies(session, search=search)


async def _get_or_404(session: AsyncSession, reply_id: uuid.UUID) -> ConversationSavedReply:
    reply = await _da.get_saved_reply_by_id(session, reply_id)
    if reply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved reply not found.")
    return reply


async def _ensure_can_modify(
    session: AsyncSession,
    reply: ConversationSavedReply,
    *,
    actor_id: uuid.UUID,
    actor_role_id: uuid.UUID,
) -> None:
    if reply.created_by_user_id == actor_id:
        return
    if await role_has_permission(session, actor_role_id, _MANAGE_KEY):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the author or an admin can change this saved reply.",
    )


async def _commit_or_conflict(session: AsyncSession, shortcut: str | None) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The shortcut '/{shortcut}' is already used by another saved reply.",
        ) from exc


async def create_saved_reply(
    session: AsyncSession,
    *,
    payload: SavedReplyCreate,
    actor_id: uuid.UUID,
    org_id: uuid.UUID,
) -> ConversationSavedReply:
    reply = ConversationSavedReply(
        org_id=org_id,
        title=payload.title,
        body=payload.body,
        shortcut=payload.shortcut,
        created_by_user_id=actor_id,
    )
    _da.insert_saved_reply(session, reply)
    await _commit_or_conflict(session, payload.shortcut)
    await session.refresh(reply)
    await audit.log(
        "conversations.saved_reply_created",
        entity_type="conversation_saved_reply",
        entity_id=reply.id,
        user_id=actor_id,
        after=_snapshot(reply),
    )
    return reply


async def update_saved_reply(
    session: AsyncSession,
    *,
    reply_id: uuid.UUID,
    payload: SavedReplyUpdate,
    actor_id: uuid.UUID,
    actor_role_id: uuid.UUID,
) -> ConversationSavedReply:
    reply = await _get_or_404(session, reply_id)
    await _ensure_can_modify(session, reply, actor_id=actor_id, actor_role_id=actor_role_id)
    before = _snapshot(reply)
    fields = payload.model_fields_set
    if "title" in fields and payload.title is not None:
        reply.title = payload.title
    if "body" in fields and payload.body is not None:
        reply.body = payload.body
    if "shortcut" in fields:
        reply.shortcut = payload.shortcut
    reply.updated_at = datetime.now(UTC)
    await _commit_or_conflict(session, reply.shortcut)
    await session.refresh(reply)
    await audit.log(
        "conversations.saved_reply_updated",
        entity_type="conversation_saved_reply",
        entity_id=reply.id,
        user_id=actor_id,
        before=before,
        after=_snapshot(reply),
    )
    return reply


async def delete_saved_reply(
    session: AsyncSession,
    *,
    reply_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role_id: uuid.UUID,
) -> None:
    reply = await _get_or_404(session, reply_id)
    await _ensure_can_modify(session, reply, actor_id=actor_id, actor_role_id=actor_role_id)
    before = _snapshot(reply)
    await _da.delete_saved_reply_row(session, reply)
    await session.commit()
    await audit.log(
        "conversations.saved_reply_deleted",
        entity_type="conversation_saved_reply",
        entity_id=reply_id,
        user_id=actor_id,
        before=before,
    )
