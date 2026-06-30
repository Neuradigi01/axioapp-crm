"""Conversation tags service
(whatsapp-platform-upgrade Step 14).

Owns the CRUD lifecycle for ``tbl_conversation_tags`` plus the M:N
assignment writes against ``tbl_conversation_tag_assignments``.

Permission split (enforced at the router layer, not here):

  * Create / Edit / Delete → `settings.conversations.manage`
  * Assign / Unassign → `conversations.write`

The service layer trusts the caller's permission check and focuses on
the data invariants:

  * Case-insensitive uniqueness on (org, name) — DB index enforces it;
    we catch the IntegrityError and surface a 409.
  * Cascade-on-delete via the FK definitions — `delete_tag` just
    removes the parent row.
  * Idempotent assignment — re-assigning an existing tag is a no-op.

All reads/writes RLS-scope to the active org via ``TenantScoped``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations import data_access as _da
from src.app.core.conversations.models import (
    ConversationTag,
    ConversationTagAssignment,
)

logger = logging.getLogger(__name__)


# --- reads ----------------------------------------------------------------


async def list_tags(
    session: AsyncSession,
    *,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return all tags for the active org, sorted by name. The result
    carries `usage_count` (number of conversations the tag is on) so
    the manager UI can show "5 conversations" alongside the chip."""
    rows = await _da.list_tags_with_usage(session, search=search)
    return [
        {
            "id": r.id,
            "name": r.name,
            "color": r.color,
            "created_by_user_id": r.created_by_user_id,
            "created_at": r.created_at,
            "usage_count": int(r.usage_count or 0),
        }
        for r in rows
    ]


async def get_tag_or_404(session: AsyncSession, tag_id: uuid.UUID) -> ConversationTag:
    row = await _da.get_tag_by_id(session, tag_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found.",
        )
    return row


async def list_tags_for_conversation(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Embedded `tags[]` for the conversation detail view. Returns
    `[{id, name, color}, ...]` ordered by name."""
    rows = await _da.list_tag_chips_for_conversation(session, conversation_id)
    return [{"id": r.id, "name": r.name, "color": r.color} for r in rows]


async def bulk_tags_for_conversations(
    session: AsyncSession,
    conversation_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """One-shot fetch of tags for many conversations — used by the
    list endpoint so we don't N+1-query the chip data."""
    rows = await _da.bulk_list_tag_chips_for_conversations(session, conversation_ids)
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.conversation_id, []).append({"id": r.id, "name": r.name, "color": r.color})
    return out


# --- writes ---------------------------------------------------------------


async def create_tag(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    org_id: uuid.UUID,
    name: str,
    color: str,
) -> ConversationTag:
    """Create a new tag. The case-insensitive unique index surfaces
    409 on duplicate names; we catch IntegrityError to translate the
    DB error into a friendly message."""
    tag = ConversationTag(
        org_id=org_id,
        name=name.strip(),
        color=color,
        created_by_user_id=actor_id,
    )
    _da.insert_tag(session, tag)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A tag named '{name}' already exists.",
        ) from exc
    await session.refresh(tag)
    await audit.log(
        "conversations.tag_created",
        entity_type="conversation_tag",
        entity_id=tag.id,
        user_id=actor_id,
        after={"name": tag.name, "color": tag.color},
    )
    return tag


async def update_tag(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    tag_id: uuid.UUID,
    name: str | None,
    color: str | None,
) -> ConversationTag:
    """Rename and / or recolor a tag. Empty patches are a no-op (no
    audit row, no commit)."""
    tag = await get_tag_or_404(session, tag_id)
    if name is None and color is None:
        return tag
    before = {"name": tag.name, "color": tag.color}
    if name is not None:
        tag.name = name.strip()
    if color is not None:
        tag.color = color
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with this name already exists.",
        ) from exc
    await session.refresh(tag)
    await audit.log(
        "conversations.tag_updated",
        entity_type="conversation_tag",
        entity_id=tag.id,
        user_id=actor_id,
        before=before,
        after={"name": tag.name, "color": tag.color},
    )
    return tag


async def delete_tag(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> None:
    """Delete the tag + cascade-remove every assignment to it. The DB
    FK has ``ON DELETE CASCADE`` so we just drop the parent row."""
    tag = await get_tag_or_404(session, tag_id)
    snapshot = {"name": tag.name, "color": tag.color}
    await _da.delete_tag_row(session, tag)
    await session.commit()
    await audit.log(
        "conversations.tag_deleted",
        entity_type="conversation_tag",
        entity_id=tag_id,
        user_id=actor_id,
        before=snapshot,
    )


async def assign_tag(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Idempotently attach `tag_id` to `conversation_id`. Returns the
    conversation's full tag list post-assignment so the frontend can
    swap state without a follow-up fetch."""
    # Confirm both rows exist + belong to the active org (RLS already
    # filters; explicit lookup gives a friendlier 404 than relying on
    # the unique-violation surface).
    conv = await _da.get_conversation_by_id(session, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    await get_tag_or_404(session, tag_id)

    existing = await _da.get_tag_assignment(session, conversation_id=conversation_id, tag_id=tag_id)
    if existing is None:
        _da.insert_tag_assignment(
            session,
            ConversationTagAssignment(
                org_id=org_id,
                conversation_id=conversation_id,
                tag_id=tag_id,
                tagged_by_user_id=actor_id,
            ),
        )
        await session.commit()
        await audit.log(
            "conversations.tag_assigned",
            entity_type="conversation",
            entity_id=conversation_id,
            user_id=actor_id,
            after={"tag_id": str(tag_id)},
        )
    return await list_tags_for_conversation(session, conversation_id)


async def unassign_tag(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    conversation_id: uuid.UUID,
    tag_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Remove the assignment. Idempotent — unassigning a tag that
    isn't currently applied is a silent success. Returns the updated
    tag list."""
    removed = await _da.delete_tag_assignment(
        session, conversation_id=conversation_id, tag_id=tag_id
    )
    if removed > 0:
        await session.commit()
        await audit.log(
            "conversations.tag_unassigned",
            entity_type="conversation",
            entity_id=conversation_id,
            user_id=actor_id,
            before={"tag_id": str(tag_id)},
        )
    return await list_tags_for_conversation(session, conversation_id)


__all__ = [
    "assign_tag",
    "bulk_tags_for_conversations",
    "create_tag",
    "delete_tag",
    "get_tag_or_404",
    "list_tags",
    "list_tags_for_conversation",
    "unassign_tag",
    "update_tag",
]
