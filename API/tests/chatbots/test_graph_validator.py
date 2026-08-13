"""Graph validator tests — pure-Python, no DB.

Covers the synchronous checks in :func:`core.chatbots.graph.validate_graph`:
cycle detection, unknown node type, empty graph acceptance, orphan
graph acceptance. Connect-flow chain-depth is a separate DB-bound
check tested in ``test_graph_validator_db.py`` (Step 6 territory).
"""

from __future__ import annotations

import pytest

from src.app.core.chatbots.exceptions import InvalidGraph
from src.app.core.chatbots.graph import NODE_TYPES, validate_graph
from src.app.core.chatbots.schemas import ChatbotEdge, ChatbotGraph, ChatbotNode


def _node(id_: str, type_: str) -> ChatbotNode:
    return ChatbotNode(id=id_, type=type_, config={})


def _edge(id_: str, src: str, tgt: str, label: str | None = None) -> ChatbotEdge:
    return ChatbotEdge(id=id_, source=src, target=tgt, label=label)


def test_empty_graph_allowed() -> None:
    """A brand-new bot has no nodes until the operator drops one."""
    validate_graph(ChatbotGraph())


def test_single_node_allowed() -> None:
    graph = ChatbotGraph(nodes=[_node("n1", "text_button")], edges=[])
    validate_graph(graph)


def test_linear_flow_allowed() -> None:
    graph = ChatbotGraph(
        nodes=[
            _node("a", "text_button"),
            _node("b", "ask_question"),
            _node("c", "handoff_to_human"),
        ],
        edges=[_edge("e1", "a", "b"), _edge("e2", "b", "c")],
    )
    validate_graph(graph)


def test_branch_flow_allowed() -> None:
    graph = ChatbotGraph(
        nodes=[
            _node("a", "text_button"),
            _node("b1", "ask_question"),
            _node("b2", "handoff_to_human"),
        ],
        edges=[
            _edge("e1", "a", "b1", label="button_1"),
            _edge("e2", "a", "b2", label="button_2"),
        ],
    )
    validate_graph(graph)


def test_cycle_rejected() -> None:
    graph = ChatbotGraph(
        nodes=[
            _node("a", "text_button"),
            _node("b", "ask_question"),
            _node("c", "add_tag"),
        ],
        edges=[
            _edge("e1", "a", "b"),
            _edge("e2", "b", "c"),
            _edge("e3", "c", "a"),  # cycle
        ],
    )
    with pytest.raises(InvalidGraph, match="cycle"):
        validate_graph(graph)


def test_self_loop_rejected() -> None:
    graph = ChatbotGraph(
        nodes=[_node("a", "ask_question")],
        edges=[_edge("e1", "a", "a", label="answered")],
    )
    with pytest.raises(InvalidGraph, match="cycle"):
        validate_graph(graph)


def test_unknown_node_type_rejected() -> None:
    graph = ChatbotGraph(
        nodes=[_node("a", "future_node_type_that_doesnt_exist")],
        edges=[],
    )
    with pytest.raises(InvalidGraph, match="unknown type"):
        validate_graph(graph)


def test_every_declared_node_type_registers_cleanly() -> None:
    """Every node type from the Decision-5 palette validates on its own."""
    for t in NODE_TYPES:
        graph = ChatbotGraph(nodes=[_node("n1", t)], edges=[])
        validate_graph(graph)


def test_node_type_registry_has_23_types() -> None:
    """Guardrail against silent additions. If this breaks intentionally,
    bump the number here and add the new type to ``README.md``
    Decision §5."""
    assert len(NODE_TYPES) == 23


def test_pydantic_rejects_duplicate_node_ids() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate node ids"):
        ChatbotGraph(
            nodes=[_node("a", "text_button"), _node("a", "ask_question")],
            edges=[],
        )


def test_pydantic_rejects_edge_pointing_to_missing_node() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="not in nodes"):
        ChatbotGraph(
            nodes=[_node("a", "text_button")],
            edges=[_edge("e1", "a", "b")],
        )
