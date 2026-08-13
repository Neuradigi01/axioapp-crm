"""Save-target registry tests — pure-Python, no DB.

Covers:

  * The standard-fields registry's ``bot_writable=True`` flag surfaces
    the safe fields listed in Step 2 (T24 mirror).
  * :func:`validate_save_target` shape parsing + custom-field key
    regex + system-column collision guard (called without DB when the
    entity/field is a standard bot-writable one).
  * :func:`collect_save_targets_from_graph` walks the right node types.

DB-backed cases (custom-field row exists / missing) live in
``test_save_target_registry_db.py`` — deferred until the async DB
fixture pattern is set up for this module.
"""

from __future__ import annotations

import pytest

from src.app.core.chatbots.exceptions import InvalidSaveTarget
from src.app.core.chatbots.save_target_registry import (
    collect_save_targets_from_graph,
)
from src.app.core.standard_fields import registry as sf_registry


def test_bot_writable_flag_true_on_safe_contact_fields() -> None:
    """T24 mirror — safe contact fields must be surfaced by the picker."""
    keys = {d.field_key for d in sf_registry.list_bot_writable("contact")}
    assert {"full_name", "phone", "email", "source"}.issubset(keys)


def test_bot_writable_flag_false_on_tags() -> None:
    """contact.tags must NOT be bot-writable — bots use the dedicated
    ``add_tag`` action node instead."""
    keys = {d.field_key for d in sf_registry.list_bot_writable("contact")}
    assert "tags" not in keys


def test_lead_budget_bot_writable() -> None:
    keys = {d.field_key for d in sf_registry.list_bot_writable("lead")}
    assert "budget" in keys
    assert "expected_close_date" in keys


def test_lead_pipeline_stage_not_bot_writable() -> None:
    """Pipeline-stage changes should trigger downstream automations
    via a dedicated action, not a raw Ask-node write."""
    keys = {d.field_key for d in sf_registry.list_bot_writable("lead")}
    assert "pipeline_stage" not in keys


def test_walk_in_fields_bot_writable() -> None:
    keys = {d.field_key for d in sf_registry.list_bot_writable("walk_in")}
    assert {"full_name", "phone", "email", "requirement", "budget"}.issubset(keys)


def test_task_fields_not_bot_writable() -> None:
    """Bots use the dedicated ``create_task`` action, not raw field
    writes on task rows."""
    keys = {d.field_key for d in sf_registry.list_bot_writable("task")}
    assert keys == set()


def test_collect_save_targets_from_graph_finds_ask_and_set_nodes() -> None:
    graph = {
        "nodes": [
            {
                "id": "q1",
                "type": "ask_question",
                "config": {"save_to": "contact.full_name"},
            },
            {
                "id": "q2",
                "type": "ask_address",
                "config": {"save_to": "contact.custom.address"},
            },
            {
                "id": "q3",
                "type": "ask_location",
                "config": {"save_to": "contact.custom.location"},
            },
            {
                "id": "q4",
                "type": "ask_media",
                "config": {"save_to": "contact.custom.avatar_id"},
            },
            {
                "id": "s1",
                "type": "set_custom_field",
                "config": {"save_to": "contact.source", "value": "bot"},
            },
            {
                "id": "b1",
                "type": "text_button",
                "config": {"message": "hi"},
            },
        ],
        "edges": [],
    }
    targets = collect_save_targets_from_graph(graph)
    assert set(targets) == {
        "contact.full_name",
        "contact.custom.address",
        "contact.custom.location",
        "contact.custom.avatar_id",
        "contact.source",
    }


def test_collect_save_targets_ignores_missing_save_to() -> None:
    graph = {
        "nodes": [
            {"id": "q1", "type": "ask_question", "config": {}},
            {"id": "q2", "type": "ask_question", "config": {"save_to": ""}},
            {"id": "q3", "type": "ask_question", "config": {"save_to": None}},
        ],
        "edges": [],
    }
    assert collect_save_targets_from_graph(graph) == []


@pytest.mark.asyncio
async def test_validate_bad_shape_returns_422_style_error() -> None:
    """Shape errors (bad separator, wrong prefix) fail without touching
    the DB — ``session`` is unused when the check fails early."""
    from src.app.core.chatbots.save_target_registry import validate_save_target

    with pytest.raises(InvalidSaveTarget, match="entity"):
        await validate_save_target(session=None, org_id=None, qualified_key="bogus")  # type: ignore[arg-type]

    with pytest.raises(InvalidSaveTarget, match="not supported"):
        await validate_save_target(
            session=None,  # type: ignore[arg-type]
            org_id=None,  # type: ignore[arg-type]
            qualified_key="invoice.total",
        )
