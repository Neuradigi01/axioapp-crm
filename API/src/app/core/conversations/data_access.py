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
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationSavedReply,
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
    unread_only: bool = False,
    contact_id: uuid.UUID | None = None,
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

    ``unread_only=True`` restricts the result to rows where
    ``unread_count > 0`` — powers the inbox's "Unread" chip so the
    operator can see every thread with pending messages across pages
    (not just what's already loaded).
    """
    filters: list[Any] = []
    # ai_widget rows are runtime-internal — they hold the ChatRuntime's
    # per-turn context for the public embed + preview flows, not a
    # real customer conversation. They must never appear in the
    # operator inbox regardless of the caller's ``channel`` filter,
    # so we exclude them unconditionally. (Adding this filter also
    # hides any legacy widget rows that leaked in before the runtime
    # started reusing the inbox conversation for inbound AI replies.)
    filters.append(Conversation.channel != ConversationChannel.ai_widget)
    if channel is not None:
        filters.append(Conversation.channel == channel)
    if status_filter is not None:
        filters.append(Conversation.status == status_filter)
    if assigned_to_unassigned:
        filters.append(Conversation.assigned_to_id.is_(None))
    elif assigned_to_id is not None:
        filters.append(Conversation.assigned_to_id == assigned_to_id)
    if q:
        filters.append(_search_clause(q))
    if tag_ids:
        tagged_subquery = (
            select(ConversationTagAssignment.conversation_id)
            .where(ConversationTagAssignment.tag_id.in_(tag_ids))
            .scalar_subquery()
        )
        filters.append(Conversation.id.in_(tagged_subquery))
    if unread_only:
        filters.append(Conversation.unread_count > 0)
    if contact_id is not None:
        filters.append(Conversation.contact_id == contact_id)

    base = select(Conversation)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(
        Conversation.last_message_at.desc().nullslast(),
        Conversation.created_at.desc(),
    )
    return await paginate(session, base, page=page, size=size)


# Message-body search only kicks in from this length — shorter terms
# match almost every thread and can't use the trigram index.
_MESSAGE_SEARCH_MIN_LEN = 3


def _search_clause(q: str) -> Any:
    """Inbox search: a conversation matches when the term appears in its
    channel handle (phone / email), the linked contact's name / phone /
    email, or — for terms of 3+ chars — any message body on the thread
    (internal notes included, so operators can find their own notes).
    LIKE wildcards in the term are escaped so ``50%`` searches literally.
    Trigram GIN indexes back the name + message-body lookups."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    term = f"%{escaped}%"
    clauses: list[Any] = [
        Conversation.external_id.ilike(term, escape="\\"),
        Conversation.contact_id.in_(
            select(Contact.id).where(
                or_(
                    Contact.full_name.ilike(term, escape="\\"),
                    Contact.phone.ilike(term, escape="\\"),
                    Contact.email.ilike(term, escape="\\"),
                )
            )
        ),
    ]
    if len(q) >= _MESSAGE_SEARCH_MIN_LEN:
        clauses.append(
            exists(
                select(Message.id).where(
                    Message.conversation_id == Conversation.id,
                    Message.text.ilike(term, escape="\\"),
                )
            )
        )
    return or_(*clauses)


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


async def list_phone_conversations_for_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
) -> list[Conversation]:
    """Every WhatsApp/SMS conversation linked to this contact. Used by
    the phone-cascade sync so a contact-side phone edit propagates to
    the ``external_id`` snapshot on its live threads."""
    result = await session.execute(
        select(Conversation).where(
            Conversation.contact_id == contact_id,
            Conversation.channel.in_((ConversationChannel.whatsapp, ConversationChannel.sms)),
        )
    )
    return list(result.scalars().all())


async def conversation_exists_for_channel_external(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    external_id: str,
    exclude_id: uuid.UUID,
) -> bool:
    """Duplicate-guard for the phone-cascade sync — return True when
    *another* conversation already owns ``(channel, external_id)``.
    Used to skip a rename that would create a stale-duplicate pair."""
    result = await session.execute(
        select(Conversation.id)
        .where(
            Conversation.channel == channel,
            Conversation.external_id == external_id,
            Conversation.id != exclude_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# --- AI pause / resume compare-and-set (Step 3) --------------------------


async def pause_conversation_ai_cas(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    now: datetime,
) -> bool:
    """Single-statement CAS: flip ``ai_paused=false`` → ``true`` only if
    the row is currently unpaused. Returns True iff the update took
    effect. Callers translate False to a 409 with the current holder's
    details (fetched via :func:`get_conversation_ai_pause_holder`).

    Not committed by this function — the service owns the transaction
    boundary."""
    stmt = (
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.ai_paused.is_(False),
        )
        .values(
            ai_paused=True,
            ai_paused_by_user_id=actor_user_id,
            ai_paused_at=now,
        )
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


async def resume_conversation_ai_cas(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> bool:
    """Symmetric of :func:`pause_conversation_ai_cas`. Only takes
    effect when the row is currently paused; returns False when the
    caller lost the race or the conversation was never paused."""
    stmt = (
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.ai_paused.is_(True),
        )
        .values(
            ai_paused=False,
            ai_paused_by_user_id=None,
            ai_paused_at=None,
        )
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


async def get_conversation_ai_pause_holder(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> tuple[uuid.UUID | None, datetime | None]:
    """Read the current ``(ai_paused_by_user_id, ai_paused_at)`` tuple
    on a conversation. Used by the service's 409-on-race path to build
    the ``holder_user_id`` + ``holder_name`` fields the frontend toasts.
    Returns ``(None, None)`` on a wrong-org / missing row (RLS + auto
    filter keep the query scoped)."""
    result = await session.execute(
        select(Conversation.ai_paused_by_user_id, Conversation.ai_paused_at).where(
            Conversation.id == conversation_id
        )
    )
    row = result.first()
    if row is None:
        return None, None
    return row[0], row[1]


# --- Messages -----------------------------------------------------------


async def list_messages_for_conversation(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int | None = None,
    before_id: uuid.UUID | None = None,
) -> list[Message]:
    """Messages on one conversation, oldest first.

    ``limit=None`` returns the whole thread — kept for export paths
    (CSV / PDF) and any legacy caller that hasn't been updated. The
    thread-view path passes ``limit`` (default 50 at the router)
    and optionally ``before_id`` to fetch the page *older* than a
    given anchor for infinite-scroll-up.

    Keyset walk (``created_at DESC + id DESC`` then reversed) so
    paging back through a 5k-message thread doesn't scan-and-sort
    every prior page. The ``(conversation_id, created_at)`` index
    (models.py:180) covers it.
    """
    if limit is None and before_id is None:
        # Legacy fast path: whole thread ascending.
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return list((await session.execute(stmt)).scalars().all())

    stmt = select(Message).where(Message.conversation_id == conversation_id)

    if before_id is not None:
        # Resolve the anchor's timestamp so the walk is keyset-safe
        # even across ties on ``created_at`` (webhook batches can
        # land two messages with the same second).
        anchor = (
            await session.execute(
                select(Message.created_at, Message.id).where(Message.id == before_id)
            )
        ).one_or_none()
        if anchor is not None:
            anchor_created_at, anchor_id = anchor
            stmt = stmt.where(
                (Message.created_at < anchor_created_at)
                | ((Message.created_at == anchor_created_at) & (Message.id < anchor_id))
            )

    stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)

    # Fetch newest-first for keyset efficiency, then flip so the UI
    # renders oldest-first the way the thread view expects.
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


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


async def get_message_by_channel_id_org_scoped(
    session: AsyncSession,
    *,
    channel_message_id: str,
) -> Message | None:
    """Reverse lookup by Meta wamid without a known conversation_id.
    Used by the WhatsApp status-webhook path where the payload only
    carries the wamid + the receiving phone; org scoping is enforced
    by the RLS policy set from the router's ``set_context()`` call.
    Meta wamids are globally unique so a single-row match is safe."""
    return (
        await session.execute(
            select(Message).where(Message.channel_message_id == channel_message_id)
        )
    ).scalar_one_or_none()


async def get_last_inbound_message(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Message | None:
    """Newest ``direction='in'`` message on this conversation, or
    ``None`` if the thread has no inbounds. Used by the email-reply
    path to auto-thread the outgoing MIME on the customer's freshest
    message. Single-row lookup on the
    ``(conversation_id, created_at)`` index."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.in_)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


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


async def count_inbound_messages_before(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    exclude_message_id: uuid.UUID,
) -> int:
    """Count ``direction='in'`` messages on the conversation OTHER than
    the one just inserted (``exclude_message_id``). Used by
    ``tasks/chatbot-builder`` Step 4 to derive the ``is_first_message``
    flag on the inbound-event payload — ``count == 0`` at the moment
    the freshly-inserted inbound row is excluded means "this is the
    first inbound on the conversation"."""
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.in_)
        .where(Message.id != exclude_message_id)
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


def insert_message(session: AsyncSession, message: Message) -> None:
    """Register an already-constructed Message for INSERT."""
    session.add(message)


async def bulk_last_message_preview_for_conversations(
    session: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str | None, MessageDirection]]:
    """Return the latest external (non-internal-note) message per
    conversation as ``(snippet, direction)`` — a whitespace-collapsed
    140-char body (None for attachment-only messages) plus who sent it.
    The inbox list renders the preview line from the snippet and the
    "waiting for reply" indicator from the direction.

    Uses PostgreSQL ``DISTINCT ON`` so the whole batch resolves in one
    round-trip regardless of how many conversations are on the page.
    """
    if not conversation_ids:
        return {}
    stmt = (
        select(Message.conversation_id, Message.text, Message.direction)
        .where(Message.conversation_id.in_(conversation_ids))
        .where(Message.is_internal.is_(False))
        .distinct(Message.conversation_id)
        .order_by(Message.conversation_id, Message.created_at.desc())
    )
    result = await session.execute(stmt)
    out: dict[uuid.UUID, tuple[str | None, MessageDirection]] = {}
    for conv_id, text, direction in result.all():
        snippet: str | None = None
        if text is not None:
            collapsed = " ".join(text.split())
            snippet = collapsed if len(collapsed) <= 140 else collapsed[:139] + "…"
        out[conv_id] = (snippet, direction)
    return out


async def count_unread_conversations(session: AsyncSession, *, user_uuid: uuid.UUID) -> Row:
    """One-row aggregate of conversations with unread messages for the
    inbox badges: ``(all, mine, unassigned, whatsapp, email)``. Closed
    conversations and runtime-internal ``ai_widget`` rows are excluded."""
    unread = Conversation.unread_count > 0
    stmt = select(
        func.count().filter(unread).label("all"),
        func.count().filter(unread, Conversation.assigned_to_id == user_uuid).label("mine"),
        func.count().filter(unread, Conversation.assigned_to_id.is_(None)).label("unassigned"),
        func.count()
        .filter(unread, Conversation.channel == ConversationChannel.whatsapp)
        .label("whatsapp"),
        func.count()
        .filter(unread, Conversation.channel == ConversationChannel.email)
        .label("email"),
    ).where(
        Conversation.status != ConversationStatus.closed,
        Conversation.channel != ConversationChannel.ai_widget,
    )
    return (await session.execute(stmt)).one()


async def list_conversations_by_ids(
    session: AsyncSession, conversation_ids: list[uuid.UUID]
) -> list[Conversation]:
    """Fetch many conversations in one query (bulk actions). Ids from
    another org are filtered out by the tenant scope + RLS."""
    if not conversation_ids:
        return []
    result = await session.execute(
        select(Conversation).where(Conversation.id.in_(conversation_ids))
    )
    return list(result.scalars().all())


async def list_tagged_conversation_ids(
    session: AsyncSession, *, tag_id: uuid.UUID, conversation_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of ``conversation_ids`` already carry ``tag_id`` (bulk tag)."""
    if not conversation_ids:
        return set()
    result = await session.execute(
        select(ConversationTagAssignment.conversation_id).where(
            ConversationTagAssignment.tag_id == tag_id,
            ConversationTagAssignment.conversation_id.in_(conversation_ids),
        )
    )
    return set(result.scalars().all())


async def list_due_snoozed_conversations(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[Conversation]:
    """Snoozed conversations whose ``snoozed_until`` has passed — the
    beat sweeper reopens them. Runs outside any request context, so the
    caller's session is not tenant-scoped; every org is swept."""
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.status == ConversationStatus.snoozed,
            Conversation.snoozed_until.is_not(None),
            Conversation.snoozed_until <= now,
        )
        .order_by(Conversation.snoozed_until)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_active_member_uuids(session: AsyncSession, *, org_id: uuid.UUID) -> list[uuid.UUID]:
    """Legacy user UUIDs of every active member of ``org_id`` — the
    audience for org-wide inbox refresh pushes."""
    result = await session.execute(
        select(User.legacy_uuid)
        .join(OrganizationMember, OrganizationMember.user_member_id == User.id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
    )
    return [u for u in result.scalars().all() if u is not None]


# --- Saved replies --------------------------------------------------------


async def list_saved_replies(
    session: AsyncSession, *, search: str | None = None
) -> list[ConversationSavedReply]:
    """Every saved reply in the active org, ordered by title. ``search``
    matches title, body or shortcut (case-insensitive)."""
    stmt = select(ConversationSavedReply)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                ConversationSavedReply.title.ilike(term),
                ConversationSavedReply.body.ilike(term),
                ConversationSavedReply.shortcut.ilike(term),
            )
        )
    stmt = stmt.order_by(func.lower(ConversationSavedReply.title))
    return list((await session.execute(stmt)).scalars().all())


async def get_saved_reply_by_id(
    session: AsyncSession, reply_id: uuid.UUID
) -> ConversationSavedReply | None:
    result = await session.execute(
        select(ConversationSavedReply).where(ConversationSavedReply.id == reply_id)
    )
    return result.scalar_one_or_none()


def insert_saved_reply(session: AsyncSession, reply: ConversationSavedReply) -> None:
    session.add(reply)


async def delete_saved_reply_row(session: AsyncSession, reply: ConversationSavedReply) -> None:
    await session.delete(reply)


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


async def get_user_display_names_bulk(
    session: AsyncSession,
    *,
    user_uuids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Resolve a set of user UUIDs to display names in one query.

    Deliberately NOT org-scoped and NOT filtered by ``is_active``: the
    caller (``list_messages``) enriches historical note/message rows so
    the bubble still shows "Ajay Gogane" for a rep who has since been
    removed from the org — otherwise the frontend's active-only
    ``staffById`` map would drop back to "Unknown user".

    Falls back to email when both name parts are blank.
    """
    uuids = list(user_uuids)
    if not uuids:
        return {}
    rows = (
        await session.execute(
            select(
                User.legacy_uuid,
                UserInfo.first_name,
                UserInfo.last_name,
                UserInfo.email,
            )
            .join(UserInfo, UserInfo.member_id == User.id)
            .where(User.legacy_uuid.in_(uuids))
        )
    ).all()
    out: dict[uuid.UUID, str] = {}
    for user_uuid, first, last, email in rows:
        name = f"{(first or '').strip()} {(last or '').strip()}".strip()
        out[user_uuid] = name or email
    return out


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
    "bulk_last_message_preview_for_conversations",
    "bulk_list_tag_chips_for_conversations",
    "count_unread_conversations",
    "delete_saved_reply_row",
    "get_saved_reply_by_id",
    "insert_saved_reply",
    "list_active_member_uuids",
    "list_conversations_by_ids",
    "list_due_snoozed_conversations",
    "list_saved_replies",
    "list_tagged_conversation_ids",
    "count_outbound_messages_for_conversation",
    "delete_tag_assignment",
    "delete_tag_row",
    "find_conversation_for_channel_external",
    "get_conversation_by_id",
    "get_last_inbound_message",
    "get_message_by_channel_id_org_scoped",
    "get_message_by_channel_message_id",
    "get_message_by_id",
    "get_tag_assignment",
    "get_tag_by_id",
    "get_conversation_ai_pause_holder",
    "get_user_display_names_bulk",
    "conversation_exists_for_channel_external",
    "insert_conversation",
    "insert_message",
    "list_phone_conversations_for_contact",
    "insert_tag",
    "insert_tag_assignment",
    "list_active_members_with_names",
    "list_conversations_query",
    "list_messages_for_conversation",
    "list_tag_chips_for_conversation",
    "list_tags_with_usage",
    "pause_conversation_ai_cas",
    "resume_conversation_ai_cas",
]
