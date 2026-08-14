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
from src.app.core.chatbots import engine as _engine
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
        new_version = bot.version_number + 1
        updates["version_number"] = new_version
        # Version-history rows represent the state AT that version
        # number — so save N writes row N with the *new* payload,
        # not row N-1 with the prior state. This keeps rollback
        # semantics clean and avoids the unique-constraint collision
        # with the version-1 row that `create_chatbot_service`
        # (and imports / seeds) write at bot creation time.
        new_graph = (
            payload.graph.model_dump() if graph_changed else bot.graph
        )
        new_trigger = (
            payload.trigger_config.model_dump() if trigger_changed else bot.trigger_config
        )
        await dal.insert_chatbot_version(
            session,
            org_id=org_id,
            chatbot_id=bot.id,
            version_number=new_version,
            graph=new_graph,
            trigger_config=new_trigger,
            change_note=payload.change_note,
            created_by_user_id=actor_user_id,
        )

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

    # Version-history row represents the state AT the new version
    # number (post-rollback), matching the save-flow semantics — so
    # the row records the RESTORED blobs, not the pre-rollback ones,
    # and there's no collision with the pre-existing row at
    # `bot.version_number` (see `save_chatbot_service` for the same
    # reasoning).
    new_version = bot.version_number + 1
    await dal.insert_chatbot_version(
        session,
        org_id=org_id,
        chatbot_id=bot.id,
        version_number=new_version,
        graph=version.graph,
        trigger_config=version.trigger_config,
        change_note=f"rolled back to v{version.version_number}",
        created_by_user_id=actor_user_id,
    )

    await dal.update_chatbot_fields(
        session,
        bot=bot,
        updates={
            "graph": version.graph,
            "trigger_config": version.trigger_config,
            "version_number": new_version,
        },
        updated_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)
    return bot


# --- Export / Import (Step 15) -------------------------------------------


async def export_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
) -> dict[str, Any]:
    """Serialise a bot to the portable export envelope. No org UUIDs,
    user emails, HMAC keys, or run history leak through — only the
    minimum required to reconstruct the bot in a different org.

    Custom-field references are extracted by walking the graph for
    ``save_to`` values matching ``contact.custom.<key>`` /
    ``lead.custom.<key>``; the importer uses these to detect missing
    fields in the target org.
    """
    from datetime import UTC, datetime

    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)

    from src.app.core.chatbots.save_target_registry import (
        collect_save_targets_from_graph,
    )

    save_targets = collect_save_targets_from_graph(bot.graph or {})
    referenced_custom: list[dict[str, Any]] = []
    for qk in save_targets:
        if ".custom." in qk:
            entity, _, key = qk.split(".", 2)
            referenced_custom.append({"entity": entity, "field_key": key})

    referenced_templates: list[dict[str, Any]] = []
    for node in (bot.graph or {}).get("nodes", []):
        if node.get("type") != "template":
            continue
        tid = (node.get("config") or {}).get("template_id")
        if tid:
            referenced_templates.append({"template_id": str(tid)})

    from src.app.core.tenants import data_access as tenants_da

    org = await tenants_da.get_organization_by_id(session, org_id)
    org_name = getattr(org, "name", "Unknown") or "Unknown"

    return {
        "chatbot_export_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_org_name": org_name,
        "bot": {
            "name": bot.name,
            "description": bot.description,
            "category": bot.category,
            "priority": bot.priority,
            "trigger_config": bot.trigger_config,
            "graph": bot.graph,
            "referenced_custom_fields": referenced_custom,
            "referenced_templates": referenced_templates,
        },
    }


async def import_chatbot_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope: dict[str, Any],
    name_override: str | None,
    actor_user_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Create a new bot in ``org_id`` from an export envelope. Returns
    ``{created_bot_id, conflicts}``.

    Conflicts are informational — a missing custom-field / template
    doesn't block the import; the bot lands as a draft and the
    operator wires the references before publishing.
    """
    version = envelope.get("chatbot_export_version")
    if version != 1:
        raise InvalidGraph(
            f"unsupported chatbot_export_version: {version!r} (expected 1)"
        )

    bot_payload = envelope.get("bot") or {}
    if not isinstance(bot_payload, dict) or not bot_payload.get("name"):
        raise InvalidGraph("envelope.bot is missing or has no name")

    conflicts: list[dict[str, str]] = []

    # Custom-field conflicts — missing fields in the target org.
    referenced_custom = bot_payload.get("referenced_custom_fields") or []
    for ref in referenced_custom:
        entity = ref.get("entity")
        field_key = ref.get("field_key")
        if not entity or not field_key:
            continue
        cf = await dal.get_custom_field_by_key(
            session, org_id=org_id, entity_type=entity, field_key=field_key
        )
        if cf is None:
            conflicts.append(
                {
                    "kind": "missing_custom_field",
                    "detail": f"{entity}.custom.{field_key}",
                }
            )

    # Template conflicts — the exporter recorded template IDs from
    # the source org; those IDs won't exist in the target org.
    # Operator remaps template references manually after import.
    for tref in bot_payload.get("referenced_templates") or []:
        tid = tref.get("template_id")
        if tid:
            conflicts.append(
                {
                    "kind": "missing_template",
                    "detail": f"template_id={tid} (remap after import)",
                }
            )

    # Name-collision — bump with " (imported)" suffix, or use the
    # override.
    final_name = (name_override or bot_payload["name"]).strip()
    existing = await dal.list_chatbots(session, org_id=org_id, search=final_name, limit=1)
    if existing[0] and any(
        (row.name or "").lower() == final_name.lower() for row in existing[0]
    ):
        conflicts.append(
            {
                "kind": "name_collision",
                "detail": f"'{final_name}' already exists — appending ' (imported)'",
            }
        )
        final_name = f"{final_name} (imported)"

    # Persist as a fresh draft.
    trigger_config = bot_payload.get("trigger_config") or {}
    graph = bot_payload.get("graph") or {"nodes": [], "edges": []}
    # Regenerate node + edge ids so importing twice into the same
    # org can't collide on internal IDs. Graph-shape stays identical.
    graph = _regenerate_graph_ids(graph)

    bot = await dal.insert_chatbot(
        session,
        org_id=org_id,
        name=final_name,
        description=bot_payload.get("description"),
        category=str(bot_payload.get("category") or "Custom"),
        folder_id=None,
        priority=int(bot_payload.get("priority") or 100),
        trigger_config=trigger_config,
        graph=graph,
        created_by_user_id=actor_user_id,
    )
    await session.flush()

    await dal.insert_chatbot_version(
        session,
        org_id=org_id,
        chatbot_id=bot.id,
        version_number=1,
        graph=graph,
        trigger_config=trigger_config,
        change_note="imported",
        created_by_user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(bot)

    return {"created_bot_id": bot.id, "conflicts": conflicts}


def _regenerate_graph_ids(graph: dict[str, Any]) -> dict[str, Any]:
    """Replace node + edge IDs with fresh short random ones. Edges
    get their source/target references remapped in lockstep so the
    graph shape is preserved."""
    import secrets

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    id_map: dict[str, str] = {}
    new_nodes: list[dict[str, Any]] = []
    for node in nodes:
        old_id = node.get("id")
        if not old_id:
            continue
        new_id = f"n_{secrets.token_hex(4)}"
        id_map[old_id] = new_id
        new_nodes.append({**node, "id": new_id})
    new_edges: list[dict[str, Any]] = []
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        new_source = id_map.get(source, source)
        new_target = id_map.get(target, target)
        if new_source is None or new_target is None:
            continue
        new_edges.append(
            {
                **edge,
                "id": f"e_{secrets.token_hex(4)}",
                "source": new_source,
                "target": new_target,
            }
        )
    return {"nodes": new_nodes, "edges": new_edges}


# --- Test-fire (Step 6) ---------------------------------------------------


async def test_fire_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    chatbot_id: uuid.UUID,
    simulated_inbound_text: str,
    simulated_channel: str,
    simulated_contact_id: uuid.UUID | None,
    simulated_conversation_id: uuid.UUID | None,
    simulated_is_first_message: bool,
) -> dict[str, Any]:
    """Dry-walk a bot's graph with a synthetic inbound. Case #22 /
    Decision §17.

    * ``is_test=True`` is FORCED on the created run — no operator
      knob.
    * Handlers see ``ctx.is_test=True`` so any handler that would
      send / write skips the real dispatch and records a
      transcript-only entry (Steps 7-10 wire that behaviour).
    * The run is stepped inline (no Celery dispatch) so the caller
      gets a complete transcript on return.
    * The run row is persisted with ``is_test=true`` and swept by
      :func:`core.chatbots.tasks.sweep_test_runs` after 24h.
    """
    bot = await get_chatbot_service(session, org_id=org_id, chatbot_id=chatbot_id)

    synthetic_event = {
        "org_id": str(org_id),
        "conversation_id": (
            str(simulated_conversation_id) if simulated_conversation_id else None
        ),
        "contact_id": str(simulated_contact_id) if simulated_contact_id else None,
        "message_id": None,
        "text": simulated_inbound_text,
        "channel": simulated_channel,
        "is_first_message": simulated_is_first_message,
        "direction": "in",
    }

    run = await _engine.start_run(
        session,
        bot=bot,
        event=synthetic_event,
        is_test=True,
    )

    # Inline step loop — the engine's Celery dispatch is gated by
    # `is_test`, so we step it here up to the hard cap and return
    # whatever transcript accumulates.
    hops = 0
    while run.status == "running" and hops < 100:
        hops += 1
        await _engine.process_step(run.id)
        # Reload run — process_step opens its own session + commits.
        await session.refresh(run)

    steps = await dal.list_step_runs_for_run(
        session, org_id=org_id, run_id=run.id
    )

    return {
        "run_id": run.id,
        "final_status": run.status,
        "canceled_reason": run.canceled_reason,
        "error": run.error,
        "steps": [
            {
                "node_id": s.node_id,
                "node_type": s.node_type,
                "status": s.status,
                "output_edge_label": s.output_edge_label,
                "skip_reason": s.skip_reason,
                "error": s.error,
                "output": s.output or {},
            }
            for s in steps
        ],
    }


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
