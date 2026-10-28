"""Pin tests for the Step-2 graph validator.

Covers the 10 checks documented in :mod:`core.workflows.graph`:

  * Valid trigger+send graph passes.
  * Missing trigger → InvalidGraph.
  * Two triggers → InvalidGraph.
  * Trigger missing event_type → InvalidGraph.
  * Edge with unknown source / target → InvalidGraph (also rejected
    by Pydantic, but the validator double-checks for dict-built
    graphs).
  * Cycle → InvalidGraph.
  * Orphan node → InvalidGraph.
  * Branch node with no labelled outbound edges → InvalidGraph.
  * Wait-for-event with max_wait_seconds > 30 days → InvalidGraph.
  * Goal node missing from graph → InvalidGraph.
"""

from __future__ import annotations

import pytest

from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    register_action,
)
from src.app.core.workflows.exceptions import InvalidGraph
from src.app.core.workflows.graph import validate_graph
from src.app.core.workflows.schemas import (
    GraphEdge,
    GraphNode,
    WorkflowGraph,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Wipe + reseed the registry between cases. Steps 7-11 will
    register the real Send / Record / Routing handlers; for the
    validator tests we register a no-op factory for ``send.email``
    so the action-registry check passes."""
    _clear_registry_for_tests()
    register_action("send.email", lambda: object())
    yield
    _clear_registry_for_tests()


def _valid_trigger_send_graph() -> WorkflowGraph:
    return WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(
                id="s1",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[GraphEdge(id="e1", source="t1", target="s1")],
    )


def test_valid_graph_passes():
    graph = _valid_trigger_send_graph()
    validate_graph(graph)  # no raise


def test_missing_trigger_rejected():
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="s1",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            )
        ],
        edges=[],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "trigger" in exc.value.reason.lower()


def test_two_triggers_rejected():
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(
                id="t2",
                type="trigger.lead_status_changed",
                config={"event_type": "lead.status_changed"},
            ),
        ],
        edges=[],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "exactly one trigger" in exc.value.reason


def test_trigger_missing_event_type_rejected():
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={},
            ),
        ],
        edges=[],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "event_type" in exc.value.reason


def test_cycle_rejected():
    """A simple A → B → A cycle (no wait-back-edge) must be
    refused. Kahn's algorithm leaves visited_count < total when a
    cycle is present."""
    # Build the cycle via raw dicts so Pydantic's structural
    # checks don't intercept it (every edge references a real node).
    graph_dict = {
        "nodes": [
            {
                "id": "t1",
                "type": "trigger.lead_created",
                "position": {"x": 0, "y": 0},
                "config": {"event_type": "lead.created"},
            },
            {
                "id": "a",
                "type": "send.email",
                "position": {"x": 0, "y": 0},
                "config": {"template_id": "00000000-0000-0000-0000-000000000001"},
            },
            {
                "id": "b",
                "type": "send.email",
                "position": {"x": 0, "y": 0},
                "config": {"template_id": "00000000-0000-0000-0000-000000000001"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
            {"id": "e3", "source": "b", "target": "a"},  # cycle
        ],
    }
    graph = WorkflowGraph.model_validate(graph_dict)
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "cycle" in exc.value.reason.lower()


def test_orphan_node_rejected():
    """A send node with no inbound edge from the trigger is
    unreachable + must be rejected."""
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(
                id="reached",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
            GraphNode(
                id="orphan",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[GraphEdge(id="e1", source="t1", target="reached")],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "unreachable" in exc.value.reason.lower()


def test_branch_without_labelled_edges_rejected():
    """An ``if`` branch node MUST emit at least one outbound edge
    with a non-empty label (e.g. ``yes`` / ``no``)."""
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
                config={},
            ),
            GraphNode(
                id="s1",
                type="send.email",
                config={"template_id": "00000000-0000-0000-0000-000000000001"},
            ),
        ],
        edges=[
            GraphEdge(id="e1", source="t1", target="br"),
            # Unlabelled outbound — refused.
            GraphEdge(id="e2", source="br", target="s1"),
        ],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "branch" in exc.value.reason.lower()


def test_wait_node_over_30_days_rejected():
    """``max_wait_seconds > 30 days`` would park the run
    effectively forever — refuse at validation time."""
    graph = WorkflowGraph(
        nodes=[
            GraphNode(
                id="t1",
                type="trigger.lead_created",
                config={"event_type": "lead.created"},
            ),
            GraphNode(
                id="w1",
                type="flow.wait",
                config={"max_wait_seconds": 31 * 24 * 60 * 60},
            ),
        ],
        edges=[GraphEdge(id="e1", source="t1", target="w1")],
    )
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "30-day" in exc.value.reason


def test_goal_node_missing_rejected():
    graph = _valid_trigger_send_graph()
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph, goal_node_id="not_in_graph")
    assert "goal_node_id" in exc.value.reason


def test_unknown_action_type_rejected():
    """A node whose action type isn't on the registry should
    refuse — catches typos before publish."""
    _clear_registry_for_tests()  # Clear send.email registration.
    graph = _valid_trigger_send_graph()
    with pytest.raises(InvalidGraph) as exc:
        validate_graph(graph)
    assert "unknown action type" in exc.value.reason.lower()
