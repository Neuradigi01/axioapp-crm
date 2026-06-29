"""Graph validator for workflow definitions.

Two entry points:

  * :func:`validate_graph` — pure-Python checks. Used by tests +
    by the Pydantic-layer round-trip. Raises
    :class:`InvalidGraph` on the FIRST failure with an
    operator-friendly ``reason``.
  * :func:`validate_graph_with_db` — wraps :func:`validate_graph`
    and adds DB-bound checks: every Send-action node's
    ``template_id`` must resolve to a real
    ``tbl_message_templates`` row in the same org. Called from
    :mod:`core.workflows.service` on create/update.

Checks (per the Step-2 spec):

  1. Exactly one node of ``type='trigger'`` (the entry point).
  2. Trigger node carries a non-empty ``config.event_type``.
  3. Every edge's ``source`` and ``target`` reference existing
     node ids.
  4. No cycles. Wait-for-event nodes are special-cased — their
     single back-edge (timeout → previous node) is allowed.
  5. No orphan nodes — every non-trigger node is reachable from
     the trigger by directed traversal.
  6. ``goal_node_id`` (when set) references a node in the graph.
  7. Branch / switch nodes have at least one outbound edge with a
     non-null label.
  8. Wait-for-event nodes have a numeric
     ``config.max_wait_seconds`` ≤ 30 days.
  9. Action types referenced in nodes resolve through the action
     registry (``resolve(action_type)`` succeeds — gate against
     typos before publish).
 10. Condition nodes carry a ``config.conditions`` JSONB object
     (whose AST shape Step 6 defines — we just require the key).

Step-12 compliance pre-flight runs on top of this from the service
layer; it's NOT in this module because compliance is a deployment-
config check, not a graph-shape check.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from src.app.core.events.conditions import (
    InvalidCondition,
    validate as validate_conditions,
)
from src.app.core.workflows.actions import (
    ActionNotRegistered,
    is_registered,
    resolve as resolve_action,
)
from src.app.core.workflows.exceptions import InvalidGraph
from src.app.core.workflows.schemas import WorkflowGraph


# 30-day max wait per the spec — anything longer parks the run
# indefinitely + is almost certainly a config bug.
_MAX_WAIT_SECONDS = 30 * 24 * 60 * 60

# Node-type prefixes the validator special-cases.
_TRIGGER_TYPE = "trigger"
_BRANCH_TYPES = frozenset({"branch.if", "branch.switch"})
_WAIT_TYPES = frozenset({"flow.wait", "flow.wait_for_event"})
_CONDITION_TYPES = frozenset({"condition.if", "condition.filter"})
# Wait-for-event nodes emit one labelled `timeout` edge that may
# legally back-flow to a previously-traversed node. The cycle
# detector skips edges with this label.
_WAIT_BACK_EDGE_LABEL = "timeout"


def validate_graph(graph: WorkflowGraph, *, goal_node_id: str | None = None) -> None:
    """Pure-Python graph validation. Raises
    :class:`InvalidGraph` on the FIRST failed check.

    Pydantic's :class:`WorkflowGraph` already enforced:
      * No duplicate node ids.
      * No duplicate edge ids.
      * Every edge's source + target referenced an existing node.

    This validator layers the semantic rules on top."""
    nodes = list(graph.nodes)
    edges = list(graph.edges)

    if not nodes:
        raise InvalidGraph("workflow.graph must contain at least one node")

    # --- 1. Exactly one trigger node ---------------------------------
    triggers = [n for n in nodes if (n.type or "").startswith(_TRIGGER_TYPE)]
    if len(triggers) == 0:
        raise InvalidGraph("workflow.graph must contain a trigger node")
    if len(triggers) > 1:
        raise InvalidGraph(
            "workflow.graph must contain exactly one trigger node; "
            f"found {len(triggers)}"
        )
    trigger = triggers[0]

    # --- 2. Trigger carries an event_type ----------------------------
    event_type = (trigger.config or {}).get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise InvalidGraph(
            f"trigger node '{trigger.id}' missing non-empty "
            "config.event_type"
        )

    # --- 3. Edges reference existing node ids ------------------------
    # (Pydantic already enforced this for source + target; we keep
    #  the check here as a defence-in-depth so the validator is
    #  safe to call against dict-built graphs in tests.)
    node_ids: set[str] = {n.id for n in nodes}
    for e in edges:
        if e.source not in node_ids:
            raise InvalidGraph(
                f"edge '{e.id}' references unknown source node '{e.source}'"
            )
        if e.target not in node_ids:
            raise InvalidGraph(
                f"edge '{e.id}' references unknown target node '{e.target}'"
            )

    # --- 4. No cycles (Kahn's algo, skipping wait-back edges) --------
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}
    for e in edges:
        # Wait-for-event timeout edges are allowed to back-flow.
        if e.label == _WAIT_BACK_EDGE_LABEL:
            continue
        adjacency[e.source].append(e.target)
        in_degree[e.target] = in_degree.get(e.target, 0) + 1

    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
    visited_count = 0
    while queue:
        current = queue.popleft()
        visited_count += 1
        for nxt in adjacency[current]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    if visited_count != len(nodes):
        raise InvalidGraph(
            "workflow.graph contains a cycle (only wait-for-event "
            "timeout edges may back-flow)"
        )

    # --- 5. No orphan nodes ------------------------------------------
    # Directed reachability from the trigger (ignoring back-edges
    # so the wait pattern doesn't falsely "save" a downstream
    # orphan).
    forward: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.label == _WAIT_BACK_EDGE_LABEL:
            continue
        forward[e.source].append(e.target)
    reachable: set[str] = {trigger.id}
    stack: list[str] = [trigger.id]
    while stack:
        current = stack.pop()
        for nxt in forward[current]:
            if nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)
    unreachable = node_ids - reachable
    if unreachable:
        sample = sorted(unreachable)[:3]
        raise InvalidGraph(
            "workflow.graph has unreachable nodes: " + ", ".join(sample)
        )

    # --- 6. goal_node_id (when set) exists ---------------------------
    if goal_node_id is not None and goal_node_id not in node_ids:
        raise InvalidGraph(
            f"goal_node_id '{goal_node_id}' not present in graph"
        )

    # --- 7. Branch / switch nodes have labelled outbound edges -------
    outbound_by_source: dict[str, list[Any]] = defaultdict(list)
    for e in edges:
        outbound_by_source[e.source].append(e)
    for n in nodes:
        if n.type in _BRANCH_TYPES:
            outbound_labels = {
                str(e.label).strip()
                for e in outbound_by_source.get(n.id, [])
                if e.label is not None and str(e.label).strip() != ""
            }
            if not outbound_labels:
                raise InvalidGraph(
                    f"branch node '{n.id}' must have at least one outbound "
                    "edge with a non-null label"
                )
            # Step 6 — every branch / switch node MUST have an
            # explicit fallback edge so unmatched cases don't
            # silently terminate the run. ``branch.if`` → `else`;
            # ``branch.switch`` → `default`.
            fallback = (
                "default" if n.type == "branch.switch" else "else"
            )
            if fallback not in outbound_labels:
                raise InvalidGraph(
                    f"branch node '{n.id}' (type='{n.type}') must have "
                    f"an outbound edge labelled '{fallback}' as the "
                    "fallback when no branch matches"
                )

    # --- 8. Wait-for-event max_wait_seconds bound --------------------
    for n in nodes:
        if n.type in _WAIT_TYPES:
            max_wait = (n.config or {}).get("max_wait_seconds")
            if max_wait is None or not isinstance(max_wait, (int, float)):
                raise InvalidGraph(
                    f"wait node '{n.id}' missing numeric "
                    "config.max_wait_seconds"
                )
            if max_wait <= 0:
                raise InvalidGraph(
                    f"wait node '{n.id}' config.max_wait_seconds must be > 0"
                )
            if max_wait > _MAX_WAIT_SECONDS:
                raise InvalidGraph(
                    f"wait node '{n.id}' config.max_wait_seconds exceeds "
                    "30-day maximum"
                )

    # --- 9. Action types resolve through the registry ----------------
    # Trigger / branch / condition / wait nodes are handled by the
    # engine directly (no registry lookup); action.* and send.*
    # nodes go through the registry.
    for n in nodes:
        if n.type.startswith("action.") or n.type.startswith("send."):
            if not is_registered(n.type):
                raise InvalidGraph(
                    f"node '{n.id}' references unknown action type "
                    f"'{n.type}' — register the handler or fix the "
                    "node type"
                )
            try:
                resolve_action(n.type)
            except ActionNotRegistered as exc:
                raise InvalidGraph(str(exc)) from exc

    # --- 10. Condition nodes carry a conditions dict -----------------
    for n in nodes:
        if n.type in _CONDITION_TYPES:
            conditions = (n.config or {}).get("conditions")
            if not isinstance(conditions, dict):
                raise InvalidGraph(
                    f"condition node '{n.id}' missing config.conditions "
                    "(expected JSONB object)"
                )

    # --- 11. Step 6 — condition AST shape validation -----------------
    # Trigger nodes, condition nodes, and branch.if's per-branch
    # conditions all run through the shared AST. The validator
    # surfaces operator-friendly reasons at publish time so a
    # malformed condition can't sneak past into the runtime path.
    for n in nodes:
        cfg = n.config or {}
        # Trigger nodes carry conditions directly under config.
        if n.type.startswith(_TRIGGER_TYPE):
            conds = cfg.get("conditions")
            if conds is not None:
                try:
                    validate_conditions(conds)
                except InvalidCondition as exc:
                    raise InvalidGraph(
                        f"trigger node '{n.id}' has invalid conditions: "
                        f"{exc}"
                    )
        # Condition nodes — already required to carry conditions
        # above; validate the AST shape.
        if n.type in _CONDITION_TYPES:
            conds = cfg.get("conditions")
            try:
                validate_conditions(conds)
            except InvalidCondition as exc:
                raise InvalidGraph(
                    f"condition node '{n.id}' has invalid conditions: "
                    f"{exc}"
                )
        # Branch nodes — validate each branch's conditions.
        if n.type == "branch.if":
            branches = cfg.get("branches") or []
            if not isinstance(branches, list):
                raise InvalidGraph(
                    f"branch node '{n.id}' config.branches must be a list"
                )
            for i, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    raise InvalidGraph(
                        f"branch node '{n.id}' branches[{i}] must be a dict"
                    )
                branch_conds = branch.get("conditions")
                if branch_conds is None:
                    # Empty conditions are fine — they always match
                    # (useful for a final catch-all branch).
                    continue
                try:
                    validate_conditions(branch_conds)
                except InvalidCondition as exc:
                    raise InvalidGraph(
                        f"branch node '{n.id}' branches[{i}] has invalid "
                        f"conditions: {exc}"
                    )


async def validate_graph_with_db(
    session,
    *,
    org_id,
    graph: WorkflowGraph,
    goal_node_id: str | None = None,
) -> None:
    """Pure validation + DB-bound checks. The service layer calls
    this on create/update; tests prefer the pure
    :func:`validate_graph` variant when they don't have a session.

    DB-bound checks:

      * Every send-action node's ``config.template_id`` resolves to
        a real ``tbl_message_templates`` row in ``org_id``.

    Pulled in one query (``WHERE id IN (...)``), not per-node, so
    the validation cost stays O(1) DB round-trips even for large
    graphs."""
    import uuid as _uuid

    from sqlalchemy import select as _select

    from src.app.core.templates.models import MessageTemplate

    validate_graph(graph, goal_node_id=goal_node_id)

    # Collect every template id referenced by a send-action node.
    referenced_ids: list[_uuid.UUID] = []
    referenced_by_node: dict[str, _uuid.UUID] = {}
    for n in graph.nodes:
        if not (n.type.startswith("send.") or n.type.startswith("action.send.")):
            continue
        raw = (n.config or {}).get("template_id")
        if raw is None:
            raise InvalidGraph(
                f"send node '{n.id}' missing config.template_id"
            )
        try:
            tid = _uuid.UUID(str(raw))
        except (ValueError, TypeError) as exc:
            raise InvalidGraph(
                f"send node '{n.id}' has malformed template_id"
            ) from exc
        referenced_ids.append(tid)
        referenced_by_node[n.id] = tid

    if not referenced_ids:
        return

    # One DB hit covers every referenced template id, scoped to the
    # active org. Missing rows surface as the first node that
    # references them.
    rows = (
        await session.execute(
            _select(MessageTemplate.id).where(
                MessageTemplate.id.in_(referenced_ids),
                MessageTemplate.org_id == org_id,
            )
        )
    ).scalars().all()
    found: set[_uuid.UUID] = set(rows)
    for node_id, tid in referenced_by_node.items():
        if tid not in found:
            raise InvalidGraph(
                f"send node '{node_id}' references missing template "
                f"'{tid}'"
            )


__all__ = ["validate_graph", "validate_graph_with_db"]
