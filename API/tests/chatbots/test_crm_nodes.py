"""CRM extras + Connect Flow + AI stub tests — pure Python.

Covers registration + validation + AI stub behaviour. Full DB-bound
tests (create_lead persists row, book_appointment conflict path,
handoff sets assigned_to_id, connect_flow chains + carries answers)
land in ``test_crm_nodes_db.py`` — deferred to batch pytest per
memory ``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.app.core.chatbots.engine import NODE_REGISTRY


# --- Registry side-effect --------------------------------------------------


def test_all_step10_nodes_registered() -> None:
    for t in (
        "handoff_to_human",
        "create_lead",
        "book_appointment",
        "create_task",
        "connect_flow",
        "single_ai_message",
        "assign_ai_assistant",
    ):
        assert t in NODE_REGISTRY, f"node '{t}' not registered"


def test_final_registry_size_is_23() -> None:
    """All 23 node types from Decision §5 are now live. Guardrail
    against a future accidental deletion."""
    assert len(NODE_REGISTRY) == 23


# --- Handoff -------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_rejects_missing_user_id_for_specific() -> None:
    from src.app.core.chatbots.nodes.handoff_to_human import handle

    fake_ctx = _make_ctx(
        node_config={"assign_mode": "specific"},
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "user_id" in result.error


@pytest.mark.asyncio
async def test_handoff_rejects_unknown_mode() -> None:
    from src.app.core.chatbots.nodes.handoff_to_human import handle

    fake_ctx = _make_ctx(
        node_config={"assign_mode": "psychic_prediction"},
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "not supported" in result.error


@pytest.mark.asyncio
async def test_handoff_round_robin_needs_team_ids() -> None:
    from src.app.core.chatbots.nodes.handoff_to_human import handle

    fake_ctx = _make_ctx(
        node_config={"assign_mode": "round_robin"},
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "team_ids" in result.error


@pytest.mark.asyncio
async def test_handoff_specific_test_mode_returns_end_run() -> None:
    from src.app.core.chatbots.nodes.handoff_to_human import handle

    user_id = uuid.uuid4()
    fake_ctx = _make_ctx(
        node_config={"assign_mode": "specific", "user_id": str(user_id)},
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.end_run is True
    assert result.output["assigned_to_id"] == str(user_id)


# --- Create Lead ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_lead_skips_without_contact() -> None:
    from src.app.core.chatbots.nodes.create_lead import handle

    fake_ctx = _make_ctx(node_config={"source": "chatbot"}, contact_id=None)
    result = await handle(fake_ctx)
    assert result.skip_reason == "no_contact_on_run"


@pytest.mark.asyncio
async def test_create_lead_test_mode_returns_created_port() -> None:
    from src.app.core.chatbots.nodes.create_lead import handle

    fake_ctx = _make_ctx(node_config={"source": "chatbot"}, is_test=True)
    result = await handle(fake_ctx)
    assert result.next_edge_label == "created"


# --- Book Appointment ----------------------------------------------------


@pytest.mark.asyncio
async def test_book_appointment_rejects_missing_assignee() -> None:
    from src.app.core.chatbots.nodes.book_appointment import handle

    fake_ctx = _make_ctx(
        node_config={"scheduled_at_from": "answers.slot"},
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "assigned_to_user_id" in result.error


@pytest.mark.asyncio
async def test_book_appointment_missing_scheduled_at_takes_error_port() -> None:
    from src.app.core.chatbots.nodes.book_appointment import handle

    fake_ctx = _make_ctx(
        node_config={
            "assigned_to_user_id": str(uuid.uuid4()),
            "scheduled_at_from": "answers.slot",
        },
        run_context={"answers": {}},
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label == "error"
    assert result.skip_reason == "missing_scheduled_at"


@pytest.mark.asyncio
async def test_book_appointment_unparseable_datetime_takes_error() -> None:
    from src.app.core.chatbots.nodes.book_appointment import handle

    fake_ctx = _make_ctx(
        node_config={
            "assigned_to_user_id": str(uuid.uuid4()),
            "scheduled_at_from": "answers.slot",
        },
        run_context={"answers": {"slot": "next tuesday"}},
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label == "error"
    assert result.skip_reason == "unparseable_scheduled_at"


# --- Create Task ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_rejects_missing_title() -> None:
    from src.app.core.chatbots.nodes.create_task import handle

    fake_ctx = _make_ctx(node_config={})
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "title" in result.error


@pytest.mark.asyncio
async def test_create_task_rejects_bad_priority() -> None:
    from src.app.core.chatbots.nodes.create_task import handle

    fake_ctx = _make_ctx(
        node_config={"title": "T", "priority": "urgent"},
    )
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "priority" in result.error


@pytest.mark.asyncio
async def test_create_task_specific_mode_test_mode() -> None:
    from src.app.core.chatbots.nodes.create_task import handle

    user_id = uuid.uuid4()
    fake_ctx = _make_ctx(
        node_config={
            "title": "Follow up",
            "assignee_mode": "specific",
            "assignee_user_id": str(user_id),
        },
        is_test=True,
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label == "created"
    assert result.output["assigned_to_id"] == str(user_id)


# --- Connect Flow --------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_flow_rejects_missing_target() -> None:
    from src.app.core.chatbots.nodes.connect_flow import handle

    fake_ctx = _make_ctx(node_config={})
    result = await handle(fake_ctx)
    assert result.error is not None
    assert "target_bot_id" in result.error


@pytest.mark.asyncio
async def test_connect_flow_self_reference_takes_error_port() -> None:
    from src.app.core.chatbots.nodes.connect_flow import handle

    same_bot = uuid.uuid4()
    fake_ctx = _make_ctx(
        node_config={"target_bot_id": str(same_bot)},
        chatbot_id=same_bot,
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label == "error"
    assert result.skip_reason == "self_reference"


@pytest.mark.asyncio
async def test_connect_flow_chain_depth_at_5_takes_error() -> None:
    from src.app.core.chatbots.nodes.connect_flow import handle

    fake_ctx = _make_ctx(
        node_config={"target_bot_id": str(uuid.uuid4())},
        run_context={"chain_depth": 5, "answers": {}},
    )
    result = await handle(fake_ctx)
    assert result.next_edge_label == "error"
    assert result.skip_reason == "chain_depth_exceeded"


# --- AI stubs ------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_ai_message_error_port_when_provider_missing() -> None:
    """v1 always errors — either ``ai_not_configured`` or
    ``ai_send_not_implemented`` depending on the org flag. Both are
    intentional until a real LLM lands."""
    from src.app.core.chatbots.nodes.single_ai_message import handle

    # Fake tenants DAL that returns an org with the flag off.
    class _FakeOrg:
        ai_provider_configured = False

    async def _fake_get_organization_by_id(_session, _org_id):
        return _FakeOrg()

    import src.app.core.tenants.data_access as tenants_da

    orig = tenants_da.get_organization_by_id
    tenants_da.get_organization_by_id = _fake_get_organization_by_id  # type: ignore[assignment]
    try:
        result = await handle(_make_ctx(node_config={}))
    finally:
        tenants_da.get_organization_by_id = orig  # type: ignore[assignment]

    assert result.next_edge_label == "error"
    assert result.skip_reason == "ai_not_configured"


@pytest.mark.asyncio
async def test_assign_ai_assistant_error_port_when_provider_missing() -> None:
    from src.app.core.chatbots.nodes.assign_ai_assistant import handle

    class _FakeOrg:
        ai_provider_configured = False

    async def _fake_get_organization_by_id(_session, _org_id):
        return _FakeOrg()

    import src.app.core.tenants.data_access as tenants_da

    orig = tenants_da.get_organization_by_id
    tenants_da.get_organization_by_id = _fake_get_organization_by_id  # type: ignore[assignment]
    try:
        result = await handle(_make_ctx(node_config={}))
    finally:
        tenants_da.get_organization_by_id = orig  # type: ignore[assignment]

    assert result.next_edge_label == "error"
    assert result.skip_reason == "ai_not_configured"


# --- Helpers -------------------------------------------------------------


def _make_ctx(
    *,
    node_config: dict,
    is_test: bool = True,
    contact_id: uuid.UUID | None = None,
    chatbot_id: uuid.UUID | None = None,
    run_context: dict | None = None,
) -> SimpleNamespace:
    """Minimal NodeExecutionContext-shaped object for pure tests."""
    if contact_id is None and node_config.get("_no_contact") is not True:
        contact_id = uuid.uuid4()
    if chatbot_id is None:
        chatbot_id = uuid.uuid4()
    return SimpleNamespace(
        session=None,
        run=SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            chatbot_id=chatbot_id,
            conversation_id=None,
            contact_id=contact_id,
            lead_id=None,
            next_step_at=None,
        ),
        bot=SimpleNamespace(id=chatbot_id, created_by_user_id=uuid.uuid4()),
        node_id="n1",
        node_type="",
        node_config=node_config,
        run_context=run_context or {},
        is_test=is_test,
    )
