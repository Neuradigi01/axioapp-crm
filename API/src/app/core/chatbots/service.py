"""Chatbots service — orchestration + transaction boundary.

The ONLY layer that calls ``db.commit / rollback / flush / refresh``
per the layered-architecture pin-test.

Responsibilities:

  * CRUD orchestration over :mod:`data_access`.
  * Graph validation via :mod:`graph` (structural + connect-flow
    depth) before every save.
  * Save-target validation via :mod:`save_target_registry` for every
    Ask-* / Set-Custom-Field node in the graph.
  * Optimistic locking via ``expected_version`` (Case #27).
  * Version-history writes on every save.
  * Publish / pause / archive lifecycle transitions.
  * Rollback: restore a prior version's graph + trigger_config.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as dal
from src.app.core.chatbots import save_target_registry as save_targets
from src.app.core.chatbots.exceptions import (
    ChatbotNotFound,
    ChatbotVersionConflict,
    InvalidGraph,
)
from src.app.core.chatbots.graph import validate_graph_with_db
from src.app.core.chatbots.trigger_matcher import UnsafeRegex, lint_regex_pattern
from src.app.core.chatbots.models import Chatbot, ChatbotVersion
from src.app.core.chatbots.schemas import (
    ChatbotCreate,
    ChatbotGraph,
    ChatbotUpdate,
    TriggerConfig,
)


async def create_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: ChatbotCreate,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """Create a fresh bot. Runs graph + save-target + trigger-regex
    validation on the initial payload (usually empty for a brand-new
    bot, but Duplicate / Import may seed a full graph + trigger)."""
    _validate_trigger_config(payload.trigger_config)
    await _validate_graph_and_save_targets(
        session,
        org_id=org_id,
        graph=payload.graph,
        current_bot_id=None,
    )

    bot = await dal.insert_chatbot(
        session,
        org_id=org_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        folder_id=payload.folder_id,
        priority=payload.priority,
        trigger_config=payload.trigger_config.model_dump(),
        graph=payload.graph.model_dump(),
        created_by_user_id=actor_user_id,
    )
    await session.flush()

    # Version 1 snapshot so history is complete from birth.
    await dal.insert_chatbot_version(
        session,
        org_id=org_id,
        chatbot_id=bot.id,
        version_number=1,
        graph=bot.graph,
        trigger_config=bot.trigger_config,
        change_note="initial create",
        created_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)
    return bot


async def get_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
) -> Chatbot:
    """Fetch one bot; raises :class:`ChatbotNotFound` for a missing
    or cross-org id (router turns it into a 404)."""
    bot = await dal.get_chatbot(session, org_id=org_id, chatbot_id=chatbot_id)
    if bot is None:
        raise ChatbotNotFound(f"chatbot {chatbot_id} not found")
    return bot


async def list_chatbots_service(
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
    """List bots with optional filters. Thin passthrough — kept in
    service.py so future permission scoping (e.g. "editor sees own
    only") lands here without a router change."""
    return await dal.list_chatbots(
        session,
        org_id=org_id,
        status=status,
        category=category,
        folder_id=folder_id,
        search=search,
        limit=limit,
        offset=offset,
    )


async def save_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    payload: ChatbotUpdate,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """The load-bearing endpoint. Runs:

      1. Optimistic-lock check against ``expected_version``.
      2. Graph + save-target validation on the incoming graph (only
         when graph or trigger_config actually changed).
      3. Version-history append with the PRIOR blobs (so rollback
         can restore what was live just before this save).
      4. Field application + ``version_number`` bump.
      5. Single commit.
    """
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)

    if bot.version_number != payload.expected_version:
        raise ChatbotVersionConflict(
            f"stale expected_version {payload.expected_version}; "
            f"current is {bot.version_number}"
        )

    graph_changed = payload.graph is not None
    trigger_changed = payload.trigger_config is not None

    if trigger_changed:
        assert payload.trigger_config is not None
        _validate_trigger_config(payload.trigger_config)

    if graph_changed:
        graph_obj = payload.graph  # type: ignore[assignment]
        assert graph_obj is not None
        await _validate_graph_and_save_targets(
            session,
            org_id=org_id,
            graph=graph_obj,
            current_bot_id=bot.id,
        )

    if graph_changed or trigger_changed:
        # Snapshot the PRIOR state before mutating the row.
        await dal.insert_chatbot_version(
            session,
            org_id=org_id,
            chatbot_id=bot.id,
            version_number=bot.version_number,
            graph=bot.graph,
            trigger_config=bot.trigger_config,
            change_note=payload.change_note,
            created_by_user_id=actor_user_id,
        )

    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.category is not None:
        updates["category"] = payload.category
    if payload.folder_id is not None:
        updates["folder_id"] = payload.folder_id
    if payload.priority is not None:
        updates["priority"] = payload.priority
    if trigger_changed:
        assert payload.trigger_config is not None
        updates["trigger_config"] = payload.trigger_config.model_dump()
    if graph_changed:
        assert payload.graph is not None
        updates["graph"] = payload.graph.model_dump()

    if graph_changed or trigger_changed:
        updates["version_number"] = bot.version_number + 1

    if updates:
        await dal.update_chatbot_fields(
            session,
            bot=bot,
            updates=updates,
            updated_by_user_id=actor_user_id,
        )

    await session.commit()
    await session.refresh(bot)
    return bot


async def publish_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """Flip status → live. Requires the bot's graph to already be
    valid (re-validates as a belt-and-braces guard before flipping)."""
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)
    graph_obj = ChatbotGraph(**bot.graph)
    await validate_graph_with_db(
        graph_obj,
        org_id=org_id,
        session=session,
        current_bot_id=bot.id,
    )
    # Re-validate save targets too — the picker rejects sensitive
    # targets, but a custom field could have been renamed since last
    # save.
    for qk in save_targets.collect_save_targets_from_graph(bot.graph):
        await save_targets.validate_save_target(session, org_id=org_id, qualified_key=qk)

    await dal.update_chatbot_fields(
        session,
        bot=bot,
        updates={"status": "live"},
        updated_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)
    return bot


async def pause_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """Flip status → paused. Existing parked runs continue; new
    matches are blocked."""
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)
    await dal.update_chatbot_fields(
        session,
        bot=bot,
        updates={"status": "paused"},
        updated_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)
    return bot


async def archive_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """Soft-delete. Runtime cancels any parked runs (Step 6 hook);
    the bot disappears from the list page's default view."""
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)
    await dal.soft_delete_chatbot(session, bot=bot)
    bot.updated_by_user_id = actor_user_id
    await session.commit()
    await session.refresh(bot)
    return bot


async def list_versions_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    limit: int = 50,
) -> list[ChatbotVersion]:
    """List past versions, newest first. Also validates the bot
    exists in this org (400 vs 404 discrimination)."""
    await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)
    return await dal.list_versions(
        session,
        org_id=org_id,
        chatbot_id=chatbot_id,
        limit=limit,
    )


async def rollback_to_version_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> Chatbot:
    """Restore the graph + trigger_config from a past version. Bumps
    version_number + writes a fresh history row containing the
    restored blobs, so the rollback itself is auditable."""
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)
    version = await dal.get_version(
        session,
        org_id=org_id,
        chatbot_id=chatbot_id,
        version_id=version_id,
    )
    if version is None:
        raise ChatbotNotFound(f"version {version_id} not found on bot {chatbot_id}")

    # Snapshot current state before mutating.
    await dal.insert_chatbot_version(
        session,
        org_id=org_id,
        chatbot_id=bot.id,
        version_number=bot.version_number,
        graph=bot.graph,
        trigger_config=bot.trigger_config,
        change_note=f"pre-rollback snapshot (rolling back to v{version.version_number})",
        created_by_user_id=actor_user_id,
    )

    await dal.update_chatbot_fields(
        session,
        bot=bot,
        updates={
            "graph": version.graph,
            "trigger_config": version.trigger_config,
            "version_number": bot.version_number + 1,
        },
        updated_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)
    return bot


# --- internal helpers ------------------------------------------------------


def _validate_trigger_config(trigger_config: TriggerConfig) -> None:
    """Save-time regex safety gate. Pydantic already enforced the
    500-char cap + mode-vs-payload consistency; :func:`lint_regex_pattern`
    layers the ReDoS complexity linter on top (no-op when google-re2
    is installed — that engine has no ReDoS surface)."""
    if trigger_config.mode != "regex" or not trigger_config.regex_pattern:
        return
    try:
        lint_regex_pattern(trigger_config.regex_pattern)
    except UnsafeRegex as exc:
        raise InvalidGraph(f"trigger regex_pattern rejected: {exc}") from exc


async def _validate_graph_and_save_targets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    graph: ChatbotGraph,
    current_bot_id: uuid.UUID | None,
) -> None:
    """Run the two-layer validation: graph shape + save-target allow-
    list. Raises :class:`InvalidGraph` or :class:`InvalidSaveTarget`
    on the first failure; router turns either into a 422."""
    await validate_graph_with_db(
        graph,
        org_id=org_id,
        session=session,
        current_bot_id=current_bot_id,
    )
    for qk in save_targets.collect_save_targets_from_graph(graph.model_dump()):
        await save_targets.validate_save_target(
            session,
            org_id=org_id,
            qualified_key=qk,
        )
