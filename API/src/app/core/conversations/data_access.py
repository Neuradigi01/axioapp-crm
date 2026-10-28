"""Data-access layer for the conversations engine.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations are grouped by entity for navigability:

  * Conversations (``tbl_conversations``)
      get_conversation_by_id, list_conversations_query,
      find_conversation_for_channel_external, insert_conversation
  * Messages (``tbl_messages``)
      list_messages_for_conversation, get_message_by_id,
      get_message_by_channel_message_id,
      count_outbound_messages_for_conversation, insert_message
  * Tags + assignments (``tbl_conversation_tags`` +
    ``tbl_conversation_tag_assignments``)
      list_tags_with_usage, get_tag_by_id,
      list_tag_chips_for_conversation,
      bulk_list_tag_chips_for_conversations,
      get_tag_assignment, insert_tag, insert_tag_assignment,
      delete_tag_row, delete_tag_assignment
  * Note-mention validation (cross-module read against
    ``tbl_user_login`` + ``tbl_user_info`` + ``tbl_organization_members``)
      list_active_members_with_names — kept here because the
      projection shape is conversations-specific (returns ``(uuid,
      first_name, last_name)`` for the mention picker); the canonical
      users lookups remain in ``core/users/data_access.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    ConversationTag,
    ConversationTagAssignment,
    Message,
    MessageDirection,
)
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.db.pagination import paginate

# --- Conversations ------------------------------------------------------


async def get_conversation_by_id(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    return result.scalar_one_or_none()


async def list_conversations_query(
    session: AsyncSession,
    *,
    channel: ConversationChannel | None = None,
    status_filter: ConversationStatus | None = None,
    assigned_to_id: uuid.UUID | None = None,
    assigned_to_unassigned: bool = False,
    q: str | None = None,
    tag_ids: list[uuid.UUID] | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Conversation], int]:
    """Paginated filter-aware inbox query, latest message first.

    ``assigned_to_unassigned=True`` overrides ``assigned_to_id`` and
    matches rows where ``assigned_to_id IS NULL``. Service layer
    parses the ``'unassigned'`` sentinel from the wire and sets the
    flag.

    Tag filtering uses OR-semantics: a conversation matches when it
    carries at least one of the listed tag ids.
    """
    filters: list[Any] = []
    if channel is not None:
        filters.append(Conversation.channel == channel)
    if status_filter is not None:
        filters.append(Conversation.status == status_filter)
    if assigned_to_unassigned:
        filters.append(Conversation.assigned_to_id.is_(None))
    elif assigned_to_id is not None:
        filters.append(Conversation.assigned_to_id == assigned_to_id)
    if q:
        filters.append(Conversation.external_id.ilike(f"%{q}%"))
    if tag_ids:
        tagged_subquery = (
            select(ConversationTagAssignment.conversation_id)
            .where(ConversationTagAssignment.tag_id.in_(tag_ids))
            .scalar_subquery()
        )
        filters.append(Conversation.id.in_(tagged_subquery))

    base = select(Conversation)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(
        Conversation.last_message_at.desc().nullslast(),
        Conversation.created_at.desc(),
    )
    return await paginate(session, base, page=page, size=size)


async def find_conversation_for_channel_external(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    external_id: str,
) -> Conversation | None:
    """Webhook intake pre-read — locate the conversation row that owns
    ``(channel, external_id)`` so the service can decide between
    "append to existing" and "create new"."""
    return (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == channel)
            .where(Conversation.external_id == external_id)
        )
    ).scalar_one_or_none()


def insert_conversation(session: AsyncSession, conversation: Conversation) -> None:
    """Register an already-constructed Conversation for INSERT."""
    session.add(conversation)


# --- Messages -----------------------------------------------------------


async def list_messages_for_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Message]:
    """All messages on one conversation, oldest first (the inbox
    thread view's default ordering)."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_message_by_id(session: AsyncSession, message_id: uuid.UUID) -> Message | None:
    """Single-row read by PK. Used by the reply-target and reaction
    paths."""
    return (
        await session.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()


async def get_message_by_channel_message_id(
    session: AsyncSession,
    *,
    channel_message_id: str,
    conversation_id: uuid.UUID,
) -> Message | None:
    """Reverse lookup by Meta wamid scoped to one conversation. Used
    by inbound quoted-reply and reaction handlers to map wamid → our
    UUID. ``None`` when the target was sent through a different
    system (or before this conversation was attached to ours)."""
    return (
        await session.execute(
            select(Message).where(
                Message.channel_message_id == channel_message_id,
                Message.conversation_id == conversation_id,
            )
        )
    ).scalar_one_or_none()


async def count_outbound_messages_for_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> int:
    """Number of ``direction='out'`` messages on one conversation.
    Used by the "first outbound" detection that gates the contact-
    timeline activity log."""
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.out)
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


def insert_message(session: AsyncSession, message: Message) -> None:
    """Register an already-constructed Message for INSERT."""
    session.add(message)


# --- Tags ---------------------------------------------------------------


async def list_tags_with_usage(
    session: AsyncSession,
    *,
    search: str | None = None,
) -> list[Row]:
    """All tags for the active org with ``usage_count`` (number of
    conversations the tag is on), sorted by name. Outer-joined to the
    assignments table so unused tags still appear with count=0."""
    base = (
        select(
            ConversationTag.id,
            ConversationTag.name,
            ConversationTag.color,
            ConversationTag.created_by_user_id,
            ConversationTag.created_at,
            func.count(ConversationTagAssignment.id).label("usage_count"),
        )
        .outerjoin(
            ConversationTagAssignment,
            ConversationTagAssignment.tag_id == ConversationTag.id,
        )
        .group_by(ConversationTag.id)
        .order_by(ConversationTag.name.asc())
    )
    if search:
        base = base.where(ConversationTag.name.ilike(f"%{search}%"))
    return list((await session.execute(base)).all())


async def get_tag_by_id(session: AsyncSession, tag_id: uuid.UUID) -> ConversationTag | None:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(select(ConversationTag).where(ConversationTag.id == tag_id))
    ).scalar_one_or_none()


async def list_tag_chips_for_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Row]:
    """``[(id, name, color), ...]`` for the conversation detail view's
    chip strip, ordered by name."""
    return list(
        (
            await session.execute(
                select(
                    ConversationTag.id,
                    ConversationTag.name,
                    ConversationTag.color,
                )
                .join(
                    ConversationTagAssignment,
                    ConversationTagAssignment.tag_id == ConversationTag.id,
                )
                .where(ConversationTagAssignment.conversation_id == conversation_id)
                .order_by(ConversationTag.name.asc())
            )
        ).all()
    )


async def bulk_list_tag_chips_for_conversations(
    session: AsyncSession, conversation_ids: list[uuid.UUID]
) -> list[Row]:
    """One-shot ``(conversation_id, tag_id, name, color)`` rollup for
    the inbox list page so the chip data doesn't N+1 across pages."""
    if not conversation_ids:
        return []
    return list(
        (
            await session.execute(
                select(
                    ConversationTagAssignment.conversation_id,
                    ConversationTag.id,
                    ConversationTag.name,
                    ConversationTag.color,
                )
                .join(
                    ConversationTag,
                    ConversationTag.id == ConversationTagAssignment.tag_id,
                )
                .where(ConversationTagAssignment.conversation_id.in_(conversation_ids))
                .order_by(ConversationTag.name.asc())
            )
        ).all()
    )


async def get_tag_assignment(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> ConversationTagAssignment | None:
    """Existence read for the idempotent assign path. ``None`` when
    the conversation doesn't currently carry this tag."""
    return (
        await session.execute(
            select(ConversationTagAssignment).where(
                ConversationTagAssignment.conversation_id == conversation_id,
                ConversationTagAssignment.tag_id == tag_id,
            )
        )
    ).scalar_one_or_none()


def insert_tag(session: AsyncSession, tag: ConversationTag) -> None:
    """Register an already-constructed ConversationTag for INSERT."""
    session.add(tag)


def insert_tag_assignment(session: AsyncSession, assignment: ConversationTagAssignment) -> None:
    """Register an already-constructed ConversationTagAssignment for
    INSERT."""
    session.add(assignment)


async def delete_tag_row(session: AsyncSession, tag: ConversationTag) -> None:
    """Mark a ConversationTag row for DELETE. The FK has
    ``ON DELETE CASCADE`` so every assignment to this tag goes with
    it."""
    await session.delete(tag)


async def delete_tag_assignment(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> int:
    """DELETE the (conversation, tag) assignment. Returns the number
    of rows removed (0 when the tag wasn't applied; idempotent on
    the caller side)."""
    result = await session.execute(
        delete(ConversationTagAssignment).where(
            ConversationTagAssignment.conversation_id == conversation_id,
            ConversationTagAssignment.tag_id == tag_id,
        )
    )
    return result.rowcount or 0


# --- Mention validation (cross-module read) -----------------------------


async def list_active_members_with_names(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_uuids: Iterable[uuid.UUID],
) -> list[Row]:
    """For each UUID in ``user_uuids``, return ``(user_uuid,
    first_name, last_name)`` IF the user is an active member of
    ``org_id``. Missing UUIDs are simply absent from the result —
    caller decides how to surface unknowns (notes service raises 400).

    Joins ``tbl_user_login`` + ``tbl_user_info`` + ``tbl_organization_members``.
    The projection shape is conversations-specific (mention picker
    body); the canonical user lookups stay in ``core/users/data_access.py``.
    """
    uuids = list(user_uuids)
    if not uuids:
        return []
    rows = (
        await session.execute(
            select(User.legacy_uuid, UserInfo.first_name, UserInfo.last_name)
            .join(UserInfo, UserInfo.member_id == User.id)
            .join(
                OrganizationMember,
                OrganizationMember.user_member_id == User.id,
            )
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.is_active.is_(True),
                User.legacy_uuid.in_(uuids),
            )
        )
    ).all()
    return list(rows)


__all__ = [
    "bulk_list_tag_chips_for_conversations",
    "count_outbound_messages_for_conversation",
    "delete_tag_assignment",
    "delete_tag_row",
    "find_conversation_for_channel_external",
    "get_conversation_by_id",
    "get_message_by_channel_message_id",
    "get_message_by_id",
    "get_tag_assignment",
    "get_tag_by_id",
    "insert_conversation",
    "insert_message",
    "insert_tag",
    "insert_tag_assignment",
    "list_active_members_with_names",
    "list_conversations_query",
    "list_messages_for_conversation",
    "list_tag_chips_for_conversation",
    "list_tags_with_usage",
]
