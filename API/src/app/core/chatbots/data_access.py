"""Data-access layer for the chatbots module.

Pure query helpers — no transactions, no business logic, no
permission checks. Leaf module; never imports a ``service.py``.

Operations cover ``tbl_chatbots`` + ``tbl_chatbot_versions``. Meter
+ run + step_run helpers land in Step 6 (engine) when they're first
needed; keeping them out of this file until then keeps Step 2 tight.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots.models import (
    Chatbot,
    ChatbotRun,
    ChatbotTriggerDiagnostic,
    ChatbotVersion,
)
from src.app.core.custom_fields.models import CustomFieldDefinition


async def insert_chatbot(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    description: str | None,
    category: str,
    folder_id: uuid.UUID | None,
    priority: int,
    trigger_config: dict[str, Any],
    graph: dict[str, Any],
    created_by_user_id: uuid.UUID | None,
) -> Chatbot:
    """Stage a new bot row on the session. Caller commits."""
    bot = Chatbot(
        org_id=org_id,
        name=name,
        description=description,
        category=category,
        folder_id=folder_id,
        priority=priority,
        trigger_config=trigger_config,
        graph=graph,
        version_number=1,
        created_by_user_id=created_by_user_id,
        updated_by_user_id=created_by_user_id,
    )
    session.add(bot)
    return bot


async def get_chatbot(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
) -> Chatbot | None:
    """Single-row lookup by id, tenant-scoped."""
    return (
        await session.execute(
            select(Chatbot).where(
                Chatbot.org_id == org_id,
                Chatbot.id == chatbot_id,
            )
        )
    ).scalar_one_or_none()


async def list_chatbots(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: str | None = None,
    category: str | None = None,
    folder_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Chatbot], int]:
    """List bots for the org with optional filters. Returns
    ``(rows, total_count)`` so the list endpoint can populate both
    in one call. Excludes archived rows by default via the status
    filter — pass ``status='archived'`` explicitly to see them.
    """
    conditions = [Chatbot.org_id == org_id]
    if status is not None:
        conditions.append(Chatbot.status == status)
    else:
        conditions.append(Chatbot.status != "archived")
    if category is not None:
        conditions.append(Chatbot.category == category)
    if folder_id is not None:
        conditions.append(Chatbot.folder_id == folder_id)
    if search:
        conditions.append(func.lower(Chatbot.name).contains(search.lower()))

    rows = (
        (
            await session.execute(
                select(Chatbot)
                .where(*conditions)
                .order_by(Chatbot.priority.desc(), Chatbot.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await session.execute(
            select(func.count()).select_from(Chatbot).where(*conditions)
        )
    ).scalar_one()
    return list(rows), int(total)


async def count_active_bots_by_channel(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: str,
) -> int:
    """Cheap counter for the Step-5 matcher's rate-decision + for the
    list-page summary badge. ``channel`` matches
    ``trigger_config->>'channel'`` — accepts 'any' as a wildcard that
    always matches."""
    stmt = (
        select(func.count())
        .select_from(Chatbot)
        .where(
            Chatbot.org_id == org_id,
            Chatbot.status == "live",
        )
    )
    if channel != "any":
        stmt = stmt.where(
            (Chatbot.trigger_config["channel"].astext == channel)
            | (Chatbot.trigger_config["channel"].astext == "any")
        )
    return int((await session.execute(stmt)).scalar_one())


async def update_chatbot_fields(
    session: AsyncSession,
    *,
    bot: Chatbot,
    updates: dict[str, Any],
    updated_by_user_id: uuid.UUID | None,
) -> Chatbot:
    """Apply attribute updates to a bot ORM object. Caller commits.
    Non-authoritative fields only; the service owns the version-bump
    + validation orchestration."""
    for key, value in updates.items():
        setattr(bot, key, value)
    bot.updated_by_user_id = updated_by_user_id
    return bot


async def soft_delete_chatbot(
    session: AsyncSession,
    *,
    bot: Chatbot,
) -> Chatbot:
    """Mark archived + set archived_at. Caller commits."""
    from datetime import datetime, timezone

    bot.status = "archived"
    bot.archived_at = datetime.now(timezone.utc)
    return bot


async def insert_chatbot_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    version_number: int,
    graph: dict[str, Any],
    trigger_config: dict[str, Any],
    change_note: str | None,
    created_by_user_id: uuid.UUID | None,
) -> ChatbotVersion:
    """Append a version-history row. Caller commits."""
    row = ChatbotVersion(
        org_id=org_id,
        chatbot_id=chatbot_id,
        version_number=version_number,
        graph=graph,
        trigger_config=trigger_config,
        change_note=change_note,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    return row


async def list_versions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    limit: int = 50,
) -> list[ChatbotVersion]:
    """Latest N versions of a bot, newest first."""
    return list(
        (
            await session.execute(
                select(ChatbotVersion)
                .where(
                    ChatbotVersion.org_id == org_id,
                    ChatbotVersion.chatbot_id == chatbot_id,
                )
                .order_by(ChatbotVersion.version_number.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def get_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ChatbotVersion | None:
    """Single-version lookup for the rollback flow."""
    return (
        await session.execute(
            select(ChatbotVersion).where(
                ChatbotVersion.org_id == org_id,
                ChatbotVersion.chatbot_id == chatbot_id,
                ChatbotVersion.id == version_id,
            )
        )
    ).scalar_one_or_none()


# --- Cross-module read helpers (custom_fields) -----------------------------
#
# The chatbots save-target picker needs to read ``tbl_custom_field_definitions``.
# Layered convention keeps SQL execution here (in a DAL file) rather than
# in ``save_target_registry.py`` — reusable across the module's runtime
# path (Ask-* node handlers in Step 8 will call these too).


async def list_visible_custom_fields_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
) -> list[CustomFieldDefinition]:
    """Non-hidden custom fields for one entity in one org, ordered
    for a dropdown UX. Explicit ``org_id`` filter (belt to the
    tenant-filter suspenders in :mod:`shared.orm`)."""
    return list(
        (
            await session.execute(
                select(CustomFieldDefinition)
                .where(
                    CustomFieldDefinition.org_id == org_id,
                    CustomFieldDefinition.entity_type == entity_type,
                    CustomFieldDefinition.is_hidden.is_(False),
                )
                .order_by(
                    CustomFieldDefinition.display_order,
                    CustomFieldDefinition.field_key,
                )
            )
        )
        .scalars()
        .all()
    )


async def get_custom_field_by_key(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    field_key: str,
) -> CustomFieldDefinition | None:
    """Single-row lookup by ``(org_id, entity_type, field_key)`` —
    the unique triple guaranteed by the custom-fields table's own
    unique constraint. ``None`` when the field is unknown."""
    return (
        await session.execute(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.org_id == org_id,
                CustomFieldDefinition.entity_type == entity_type,
                CustomFieldDefinition.field_key == field_key,
            )
        )
    ).scalar_one_or_none()


# --- Step 5 matcher helpers -----------------------------------------------


async def list_live_bots_for_channel(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: str,
) -> list[Chatbot]:
    """Every ``status='live'`` bot in the org whose trigger config
    accepts the given inbound channel. Bots with channel ``any`` or
    matching ``channel`` are returned.

    Ordered by ``priority DESC, created_at ASC`` — the matcher's
    tiebreak order (Decision §13). Single-query enumeration; the
    matcher iterates the list in-memory.
    """
    stmt = (
        select(Chatbot)
        .where(
            Chatbot.org_id == org_id,
            Chatbot.status == "live",
            (Chatbot.trigger_config["channel"].astext == channel)
            | (Chatbot.trigger_config["channel"].astext == "any"),
        )
        .order_by(Chatbot.priority.desc(), Chatbot.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def has_active_run_for_bot_conversation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    bot_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> bool:
    """True iff a ``running`` or ``parked`` run exists for
    ``(bot_id, conversation_id)`` in this org. Idempotency guard —
    Case #1 in the README: rapid duplicate inbounds must not spawn
    parallel runs."""
    stmt = (
        select(ChatbotRun.id)
        .where(
            ChatbotRun.org_id == org_id,
            ChatbotRun.chatbot_id == bot_id,
            ChatbotRun.conversation_id == conversation_id,
            ChatbotRun.status.in_(("running", "parked")),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def insert_trigger_diagnostic(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    bot_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
    reason: str,
    detail: str | None = None,
) -> ChatbotTriggerDiagnostic:
    """Stage a diagnostics row for the matcher decision. Caller
    commits (matcher batches diagnostics with its main session
    commit)."""
    row = ChatbotTriggerDiagnostic(
        org_id=org_id,
        bot_id=bot_id,
        conversation_id=conversation_id,
        message_id=message_id,
        reason=reason,
        detail=detail,
    )
    session.add(row)
    return row
