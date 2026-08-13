"""Engine primitive tests — pure Python, no DB.

Covers the graph-walking helpers + registry contract in
:mod:`core.chatbots.engine`. Full DB-bound tests (start_run creates
row, process_step end-to-end, meter atomicity, cap enforcement,
resume_run, cancel_parked_runs_for_conversation, test-fire dry-walk)
live in ``test_engine_db.py`` — deferred to batch pytest per memory
``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.app.core.chatbots import engine
from src.app.core.chatbots.channel_bridge import is_within_wa_window
from src.app.core.chatbots.engine import (
    DEFAULT_CONVERSATION_REPLY_CAP,
    DEFAULT_ORG_REPLY_CAP,
    NODE_REGISTRY,
    NodeExecutionContext,
    NodeResult,
    _find_next_node,
    _pick_entry_node_id,
    register_node,
    resolve_handler,
)
from src.app.core.conversations.models import ConversationChannel


# --- Entry-node selection ------------------------------------------------


def test_pick_entry_returns_none_on_empty_graph() -> None:
    assert _pick_entry_node_id({}) is None
    assert _pick_entry_node_id({"nodes": [], "edges": []}) is None


def test_pick_entry_returns_single_node() -> None:
    graph = {"nodes": [{"id": "a", "type": "text_button"}], "edges": []}
    assert _pick_entry_node_id(graph) == "a"


def test_pick_entry_returns_zero_in_degree_node() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "text_button"},
            {"id": "b", "type": "ask_question"},
            {"id": "c", "type": "handoff_to_human"},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c"},
        ],
    }
    assert _pick_entry_node_id(graph) == "a"


def test_pick_entry_picks_first_when_ambiguous() -> None:
    """Two disconnected islands — pick canvas save order (first in list)."""
    graph = {
        "nodes": [
            {"id": "left", "type": "text_button"},
            {"id": "right", "type": "text_button"},
        ],
        "edges": [],
    }
    assert _pick_entry_node_id(graph) == "left"


# --- Edge following -------------------------------------------------------


def test_find_next_no_outbound_returns_none() -> None:
    graph = {"nodes": [{"id": "a", "type": "text_button"}], "edges": []}
    assert _find_next_node(graph, "a", None) is None


def test_find_next_unlabeled_edge() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "text_button"},
            {"id": "b", "type": "ask_question"},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"}],
    }
    assert _find_next_node(graph, "a", None) == "b"


def test_find_next_labeled_edge_match() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "text_button"},
            {"id": "b", "type": "ask_question"},
            {"id": "c", "type": "handoff_to_human"},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b", "label": "yes"},
            {"id": "e2", "source": "a", "target": "c", "label": "no"},
        ],
    }
    assert _find_next_node(graph, "a", "yes") == "b"
    assert _find_next_node(graph, "a", "no") == "c"


def test_find_next_labeled_edge_miss_returns_none() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "text_button"},
            {"id": "b", "type": "ask_question"},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b", "label": "yes"}],
    }
    assert _find_next_node(graph, "a", "no") is None


# --- Node registry contract ----------------------------------------------


def test_register_and_resolve_node() -> None:
    async def _dummy(ctx: NodeExecutionContext) -> NodeResult:
        return NodeResult()

    original = NODE_REGISTRY.get("_test_node")
    try:
        register_node("_test_node", _dummy)
        assert resolve_handler("_test_node") is _dummy
    finally:
        # Clean up so this test doesn't leak into others.
        if original is None:
            NODE_REGISTRY.pop("_test_node", None)
        else:
            NODE_REGISTRY["_test_node"] = original


def test_resolve_unknown_returns_none() -> None:
    assert resolve_handler("this_type_does_not_exist_ever") is None


def test_node_result_defaults() -> None:
    r = NodeResult()
    assert r.next_edge_label is None
    assert r.park_key is None
    assert r.context_patch is None
    assert r.skip_reason is None
    assert r.end_run is False
    assert r.error is None
    assert r.output == {}


# --- Reply cap defaults --------------------------------------------------


def test_default_caps_match_readme() -> None:
    assert DEFAULT_CONVERSATION_REPLY_CAP == 50
    assert DEFAULT_ORG_REPLY_CAP == 10_000


def test_send_capable_types_include_message_and_ask() -> None:
    from src.app.core.chatbots.engine import _SEND_CAPABLE_NODE_TYPES

    for t in ("text_button", "media_button", "list", "template", "ask_question"):
        assert t in _SEND_CAPABLE_NODE_TYPES

    # Non-sending nodes must NOT be in the set (or their caps would
    # be double-counted against no actual outbound).
    for t in ("condition", "delay", "add_tag", "set_custom_field", "api_request"):
        assert t not in _SEND_CAPABLE_NODE_TYPES


# --- WA 24h window helper ------------------------------------------------


@pytest.mark.asyncio
async def test_wa_window_open_when_recent_inbound() -> None:
    conv = SimpleNamespace(
        channel=ConversationChannel.whatsapp,
        last_customer_message_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert await is_within_wa_window(None, conversation=conv) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wa_window_closed_when_stale_inbound() -> None:
    conv = SimpleNamespace(
        channel=ConversationChannel.whatsapp,
        last_customer_message_at=datetime.now(UTC) - timedelta(hours=25),
    )
    assert await is_within_wa_window(None, conversation=conv) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wa_window_closed_when_null_inbound() -> None:
    """Customer never sent — treat as OUTSIDE the window so a fresh
    bot flow requires a template first send."""
    conv = SimpleNamespace(
        channel=ConversationChannel.whatsapp,
        last_customer_message_at=None,
    )
    assert await is_within_wa_window(None, conversation=conv) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wa_window_true_for_non_wa_channels() -> None:
    """Email + web + other channels have no 24h rule — helper
    always returns True so send-capable handlers don't gate on it."""
    conv = SimpleNamespace(
        channel=ConversationChannel.email,
        last_customer_message_at=None,
    )
    assert await is_within_wa_window(None, conversation=conv) is True  # type: ignore[arg-type]


# --- Public API surface --------------------------------------------------


def test_engine_exports_expected_symbols() -> None:
    """Guardrail — Steps 7-10 import these from engine. Renaming
    breaks a lot; catch it here before pytest at large."""
    for name in (
        "start_run",
        "process_step",
        "resume_run",
        "cancel_parked_runs_for_conversation",
        "register_node",
        "resolve_handler",
        "NodeResult",
        "NodeExecutionContext",
        "NODE_REGISTRY",
    ):
        assert hasattr(engine, name), f"engine.{name} missing"
