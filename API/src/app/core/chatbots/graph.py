"""Graph validator for chatbot definitions.

Two entry points:

  * :func:`validate_graph` — pure-Python semantic checks. Runs on
    every save via :mod:`core.chatbots.service`. Raises
    :class:`InvalidGraph` on the FIRST failure with an
    operator-friendly ``reason``.
  * :func:`validate_graph_with_db` — wraps :func:`validate_graph`
    and adds the DB-bound check: ``connect_flow`` chain depth ≤ 5
    across all bots in the same org (Case #33). Called by the
    service on save when the graph contains any ``connect_flow``
    node.

Checks (per README §Cases 10-11 + 33):

  1. Structural rules — Pydantic's :class:`ChatbotGraph` already
     enforced unique ids and edge-endpoint resolution.
  2. Every node ``type`` resolves in :data:`NODE_TYPES`. Rejects at
     save-time so canvas-side typos don't reach the engine.
  3. No cycles — Kahn's algorithm. A cycle inside the graph is
     always a bug (customer replies drive the flow; wait/resume
     never creates a graph cycle).
  4. ``connect_flow`` chain depth ≤ 5 (Case #33). Recursively
     resolves ``target_bot_id`` on every ``connect_flow`` node in
     the same org until we hit a leaf or exceed the cap.

Trigger card is stored separately on ``tbl_chatbots.trigger_config``
(Decision §3), so it does NOT appear as a node here — the validator
never enforces "exactly one trigger" like the workflows validator
does.

Empty graphs are allowed — an operator creating a fresh bot has an
empty canvas until they drop their first node.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque

from src.app.core.chatbots.exceptions import InvalidGraph
from src.app.core.chatbots.schemas import ChatbotGraph

# --- Node type registry ---------------------------------------------------

# Locked per README §Decision 5. Handlers registered in Steps 7-10 own
# the deeper per-node validation; the graph validator only checks that
# the type string is one we know about. Stubs (`catalog_message`,
# `single_product`, `multi_product`) ARE included so bots can carry
# them as no-op placeholder nodes — they just error at runtime with
# ``NodeNotAvailable`` (Step 7).
NODE_TYPES: frozenset[str] = frozenset(
    {
        # Messages tab (7)
        "text_button",
        "media_button",
        "list",
        "catalog_message",
        "single_product",
        "multi_product",
        "template",
        # Actions tab (12)
        "condition",
        "ask_address",
        "ask_location",
        "ask_question",
        "ask_media",
        "set_custom_field",
        "add_tag",
        "api_request",
        "single_ai_message",
        "assign_ai_assistant",
        "delay",
        "connect_flow",
        # CRM extras (4)
        "handoff_to_human",
        "create_lead",
        "book_appointment",
        "create_task",
    }
)

# Runtime chain-depth cap for `connect_flow` chains (Case #33).
_CONNECT_FLOW_MAX_CHAIN = 5


def validate_graph(graph: ChatbotGraph) -> None:
    """Pure-Python graph validation. Raises :class:`InvalidGraph` on
    the FIRST failed check.

    Callers holding an ORM object should pass ``graph=ChatbotGraph(**bot.graph)``.
    """
    nodes = list(graph.nodes)
    edges = list(graph.edges)

    if not nodes:
        # Empty graph is fine — a freshly-created bot has one before
        # the operator drops the first node.
        return

    # --- 1. Node types resolve in the registry ------------------------
    for n in nodes:
        if n.type not in NODE_TYPES:
            raise InvalidGraph(
                f"node '{n.id}' has unknown type '{n.type}'; "
                f"add the type to core/chatbots/graph.py:NODE_TYPES if adding a new node"
            )

    # --- 2. No cycles (Kahn's algorithm) ------------------------------
    node_ids: set[str] = {n.id for n in nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = dict.fromkeys(node_ids, 0)
    for e in edges:
        adjacency[e.source].append(e.target)
        in_degree[e.target] = in_degree.get(e.target, 0) + 1

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited = 0
    while queue:
        nid = queue.popleft()
        visited += 1
        for tgt in adjacency[nid]:
            in_degree[tgt] -= 1
            if in_degree[tgt] == 0:
                queue.append(tgt)

    if visited != len(node_ids):
        raise InvalidGraph(
            "graph contains a cycle — chatbot flows must be a DAG "
            "(customer replies drive the flow; a runtime loop is a config bug)"
        )


async def validate_graph_with_db(
    graph: ChatbotGraph,
    *,
    org_id: uuid.UUID,
    session,  # type: ignore[no-untyped-def]  # AsyncSession — avoid heavy import in a pure validator
    # `current_bot_id` lets the recursion skip re-checking the bot
    # currently being saved (its graph is passed directly).
    current_bot_id: uuid.UUID | None = None,
) -> None:
    """Adds the DB-bound check on top of :func:`validate_graph`:
    every ``connect_flow`` node's ``target_bot_id`` must not lead to
    a chain longer than :data:`_CONNECT_FLOW_MAX_CHAIN` bots.

    Recursive with an explicit visited set — protects against
    connect_flow cycles across bots (A → B → A).
    """
    validate_graph(graph)

    connect_targets: list[uuid.UUID] = []
    for n in graph.nodes:
        if n.type != "connect_flow":
            continue
        target = (n.config or {}).get("target_bot_id")
        if not target:
            raise InvalidGraph(
                f"connect_flow node '{n.id}' missing config.target_bot_id"
            )
        try:
            target_uuid = uuid.UUID(str(target))
        except (TypeError, ValueError) as exc:
            raise InvalidGraph(
                f"connect_flow node '{n.id}' has invalid target_bot_id '{target}'"
            ) from exc
        if current_bot_id and target_uuid == current_bot_id:
            raise InvalidGraph(
                f"connect_flow node '{n.id}' targets its own bot — self-reference not allowed"
            )
        connect_targets.append(target_uuid)

    if not connect_targets:
        return

    # Defer import so this module stays importable in pure-Python
    # unit tests that don't spin up SQLAlchemy.
    from src.app.core.chatbots import data_access as chatbots_dal

    for target_uuid in connect_targets:
        visited: set[uuid.UUID] = {current_bot_id} if current_bot_id else set()
        await _walk_connect_chain(
            target_uuid,
            org_id=org_id,
            session=session,
            depth=1,
            visited=visited,
            dal=chatbots_dal,
        )


async def _walk_connect_chain(
    bot_id: uuid.UUID,
    *,
    org_id: uuid.UUID,
    session,  # type: ignore[no-untyped-def]
    depth: int,
    visited: set[uuid.UUID],
    dal,  # type: ignore[no-untyped-def]
) -> None:
    if depth > _CONNECT_FLOW_MAX_CHAIN:
        raise InvalidGraph(
            f"connect_flow chain depth exceeds {_CONNECT_FLOW_MAX_CHAIN} — "
            f"trim the chain or restructure the flow"
        )
    if bot_id in visited:
        raise InvalidGraph(
            f"connect_flow chain forms a cycle at bot {bot_id}"
        )
    visited = visited | {bot_id}

    target_bot = await dal.get_chatbot(session, org_id=org_id, chatbot_id=bot_id)
    if target_bot is None:
        # Missing target — deleted or belongs to another org. Caller
        # deals with the 404 UX; here we just refuse to save the
        # graph that would dangle.
        raise InvalidGraph(
            f"connect_flow target bot {bot_id} not found in org"
        )

    target_graph_dict = target_bot.graph or {}
    next_targets: list[uuid.UUID] = []
    for n in target_graph_dict.get("nodes", []):
        if n.get("type") != "connect_flow":
            continue
        nxt = (n.get("config") or {}).get("target_bot_id")
        if not nxt:
            continue
        try:
            next_targets.append(uuid.UUID(str(nxt)))
        except (TypeError, ValueError):
            # Existing bot with a broken connect_flow config — skip
            # rather than block the save of the current bot. Runtime
            # will surface the error when that bot actually runs.
            continue

    for nxt in next_targets:
        await _walk_connect_chain(
            nxt,
            org_id=org_id,
            session=session,
            depth=depth + 1,
            visited=visited,
            dal=dal,
        )
