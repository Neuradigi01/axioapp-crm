"""Pin tests for the Step-6 branch + switch action handlers.

Covers:

  * Branch handler returns the FIRST matching label.
  * Falls through to ``"else"`` when no branch matches.
  * Empty branches list → ``"else"``.
  * Switch handler matches by equality on the configured path.
  * Switch handler falls through to ``"default"`` when no value
    matches or the path doesn't resolve.
  * Graph validator rejects a branch node missing the ``else``
    outbound edge.
  * Graph validator rejects a switch node missing the ``default``
    outbound edge.
  * Graph validator rejects a branch node with a malformed
    condition AST.
"""

from __future__ import annotations

import pytest

from src.app.core.workflows.actions import flow_control  # noqa: F401 — registers
from src.app.core.workflows.actions import resolve as resolve_action
from src.app.core.workflows.exceptions import InvalidGraph
from src.app.core.workflows.graph import validate_graph
from src.app.core.workflows.schemas import (
    GraphEdge,
    GraphNode,
    WorkflowGraph,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Branch handler
# ---------------------------------------------------------------------------


async def test_branch_picks_first_matching_label():
    handler = resolve_action("branch.if")
    node = {
        "id": "br",
        "type": "branch.if",
        "config": {
            "branches": [
                {
                    "label": "high",
                    "conditions": {
                        "op": "gt",
                        "path": "lead.score",
                        "value": 80,
                    },
                },
                {
                    "label": "medium",
                    "conditions": {
                        "op": "gt",
                        "path": "lead.score",
                        "value": 50,
                    },
                },
            ]
        },
    }
    context = {"lead": {"score": 90}}
    result = await handler(None, run=None, step_run=None, node=node, context=context)
    assert result.next_edge_label == "high"

    context_med = {"lead": {"score": 60}}
    result_med = await handler(None, run=None, step_run=None, node=node, context=context_med)
    assert result_med.next_edge_label == "medium"


async def test_branch_falls_through_to_else():
    handler = resolve_action("branch.if")
    node = {
        "id": "br",
        "type": "branch.if",
        "config": {
            "branches": [
                {
                    "label": "high",
                    "conditions": {
                        "op": "gt",
                        "path": "lead.score",
                        "value": 80,
                    },
                },
            ]
        },
    }
    context = {"lead": {"score": 30}}
    result = await handler(None, run=None, step_run=None, node=node, context=context)
    assert result.next_edge_label == "else"


async def test_branch_empty_config_falls_through_to_else():
    handler = resolve_action("branch.if")
    node = {"id": "br", "type": "branch.if", "config": {}}
    result = await handler(None, run=None, step_run=None, node=node, context={})
    assert result.next_edge_label == "else"


# ---------------------------------------------------------------------------
# Switch handler
# ---------------------------------------------------------------------------


async def test_switch_matches_by_value():
    handler = resolve_action("branch.switch")
    node = {
        "id": "sw",
        "type": "branch.switch",
        "config": {
            "path": "lead.source",
            "branches": [
                {"label": "google_ads", "value": "google"},
                {"label": "meta_ads", "value": "meta"},
            ],
        },
    }
    result_g = await handler(
        None,
        run=None,
        step_run=None,
        node=node,
        context={"lead": {"source": "google"}},
    )
    assert result_g.next_edge_label == "google_ads"

    result_m = await handler(
        None,
        run=None,
        step_run=None,
        node=node,
        context={"lead": {"source": "meta"}},
    )
    assert result_m.next_edge_label == "meta_ads"


async def test_switch_falls_through_to_default_on_no_match():
    handler = resolve_action("branch.switch")
    node = {
        "id": "sw",
        "type": "branch.switch",
        "config": {
            "path": "lead.source",
            "branches": [{"label": "google_ads", "value": "google"}],
        },
    }
    result = await handler(
        None,
        run=None,
        step_run=None,
        node=node,
        context={"lead": {"source": "walk_in"}},
    )
    assert result.next_edge_label == "default"


async def test_switch_missing_path_returns_default():
    handler = resolve_action("branch.switch")
    node = {
        "id": "sw",
        "type": "branch.switch",
        "config": {
            "path": "lead.missing",
            "branches": [{"label": "x", "value": "y"}],
        },
    }
    result = await handler(None, run=None, step_run=None, node=node, context={"lead": {}})
    assert result.next_edge_label == "default"


# ---------------------------------------------------------------------------
# Graph-validator requires the fallback edge
# ---------------------------------------------------------------------------


def test_branch_node_missing_else_edge_rejected():
    """The validator must refuse a branch.if node whose outbound
    edges don't include an ``else`` label."""
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(id="br", type="branch.if", config={}),
            GraphNode(
                id="hi",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[
            GraphEdge(id="e1", source="t1", target="br"),
            GraphEdge(id="e2", source="br", target="hi", label="high"),
        ],
    )
    # Pre-register send.email so the action-registry check passes.
    from src.app.core.workflows.actions import (
        _clear_registry_for_tests,
        _register_builtins,
        register_action,
    )

    _clear_registry_for_tests()
    _register_builtins()
    register_action("send.email", lambda: object())

    try:
        with pytest.raises(InvalidGraph) as exc:
            validate_graph(graph)
        assert "'else'" in exc.value.reason
    finally:
        _clear_registry_for_tests()
        _register_builtins()


def test_switch_node_missing_default_edge_rejected():
    """branch.switch fallback label is ``default`` (not ``else``)."""
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(id="sw", type="branch.switch", config={}),
            GraphNode(
                id="g",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[
            GraphEdge(id="e1", source="t1", target="sw"),
            GraphEdge(id="e2", source="sw", target="g", label="google"),
        ],
    )
    from src.app.core.workflows.actions import (
        _clear_registry_for_tests,
        _register_builtins,
        register_action,
    )

    _clear_registry_for_tests()
    _register_builtins()
    register_action("send.email", lambda: object())

    try:
        with pytest.raises(InvalidGraph) as exc:
            validate_graph(graph)
        assert "'default'" in exc.value.reason
    finally:
        _clear_registry_for_tests()
        _register_builtins()


def test_graph_validator_rejects_malformed_branch_condition():
    """A branch.if node whose branches[].conditions has an unknown
    op surfaces as InvalidGraph at publish time."""
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(
                id="br",
                type="branch.if",
                config={
                    "branches": [
                        {
                            "label": "high",
                            "conditions": {
                                "op": "wat",
                                "path": "lead.score",
                                "value": 80,
                            },
                        }
                    ]
                },
            ),
            GraphNode(
                id="hi",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[
            GraphEdge(id="e1", source="t1", target="br"),
            GraphEdge(id="e2", source="br", target="hi", label="high"),
            GraphEdge(id="e3", source="br", target="hi", label="else"),
        ],
    )
    from src.app.core.workflows.actions import (
        _clear_registry_for_tests,
        _register_builtins,
        register_action,
    )

    _clear_registry_for_tests()
    _register_builtins()
    register_action("send.email", lambda: object())

    try:
        with pytest.raises(InvalidGraph) as exc:
            validate_graph(graph)
        assert "invalid conditions" in exc.value.reason
    finally:
        _clear_registry_for_tests()
        _register_builtins()
