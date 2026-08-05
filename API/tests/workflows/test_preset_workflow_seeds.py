"""Pin tests for Step 2 of ``tasks/workflows-absorb-automation/`` —
the ``install_preset_workflows`` orchestrator that replaces the
automation seed on new-org creation.

Coverage:

  * Pure translator (``_build_preset_graph``) — trigger→send layout,
    optional ``flow.wait`` when delay > 0.
  * Spec table integrity — the ten canonical names are present.
  * Orchestrator — installs ten active workflows on a fresh org;
    idempotent; preserves per-spec configuration (channel /
    recipient_resolver / conditions).
  * Integration — ``create_organization`` now runs
    ``install_preset_workflows`` (not ``install_default_org_seeds``),
    so a fresh org lands with 10+ workflows and 0 automations.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy import text as sql_text

from src.app.core.automation.models import AutomationTrigger
from src.app.core.tenants.service import create_organization
from src.app.core.workflows.models import Workflow, WorkflowStatus
from src.app.core.workflows.seeds import (
    _PRESET_SPECS,
    PRESET_WORKFLOW_NAMES,
    _build_preset_graph,
    install_preset_workflows,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Pure translator
# ---------------------------------------------------------------------------


def test_build_preset_graph_no_delay_produces_two_node_dag():
    """delay_seconds=0 → trigger → send. No wait node. One edge."""
    spec = next(s for s in _PRESET_SPECS if s.name == "User Welcome")
    template_id = str(uuid.uuid4())

    graph = _build_preset_graph(spec, template_id=template_id)

    node_types = [n["type"] for n in graph["nodes"]]
    assert node_types == ["trigger", "send.email"]
    assert len(graph["edges"]) == 1

    trigger, send = graph["nodes"]
    assert trigger["config"]["event_type"] == "user.signed_up"
    assert send["config"]["template_id"] == template_id
    # User Welcome uses the ``custom`` resolver against the payload path
    # (workflow's stock ``user.email`` resolver needs a user_id, which a
    # signup-event payload doesn't carry).
    assert send["config"]["recipient"] == {"kind": "custom", "path": "user.email"}


def test_build_preset_graph_positive_delay_inserts_wait_node():
    """delay_seconds>0 → trigger → flow.wait → send. Wait node carries
    both ``delay_seconds`` (engine's preferred key) and
    ``max_wait_seconds`` (graph validator's required key). None of the
    ten canonical presets set delay_seconds, so we synthesise a spec
    here — the shape is what matters."""
    from src.app.core.workflows.seeds import _PresetSpec

    spec = _PresetSpec(
        name="Test",
        event_type="lead.created",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        delay_seconds=3600,
        template_seeder="seed_user_welcome_template",  # unused in this test
    )
    graph = _build_preset_graph(spec, template_id=str(uuid.uuid4()))

    node_types = [n["type"] for n in graph["nodes"]]
    assert node_types == ["trigger", "flow.wait", "send.email"]
    assert len(graph["edges"]) == 2

    wait = graph["nodes"][1]
    assert wait["config"]["delay_seconds"] == 3600
    assert wait["config"]["max_wait_seconds"] == 3600


# ---------------------------------------------------------------------------
# Spec table integrity
# ---------------------------------------------------------------------------


def test_preset_specs_contains_the_ten_canonical_names():
    """Regression pin: the preset spec table must contain the exact
    ten ex-automation names. Adding or removing without a
    corresponding backfill migration change breaks operator
    expectations across every existing org."""
    expected = {
        "User Welcome",
        "Lead Confirmation",
        "Appointment Booked",
        "Appointment Reminder 24h",
        "Appointment Reminder 1h",
        "Invoice Sent",
        "Invoice Paid",
        "Invoice Overdue 7d",
        "Contact Birthday",
        "Lead Stale 30d",
    }
    assert set(PRESET_WORKFLOW_NAMES) == expected
    assert len(_PRESET_SPECS) == 10


# ---------------------------------------------------------------------------
# Orchestrator — behavioural tests against real tables
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    """Fresh empty org — the seed helpers run against a clean slate."""
    org = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org), "name": "PresetSeedDemo", "slug": f"psd-{org.hex[:6]}"},
    )
    await test_db.commit()
    return org


async def test_install_preset_workflows_creates_ten_active_rows(test_db, org_id):
    """A fresh org gets exactly ten preset workflows, all
    ``status='active'``, all in the ``'Preset Workflow'`` category."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()

        rows = list(
            (await test_db.execute(select(Workflow).where(Workflow.org_id == org_id))).scalars()
        )
    finally:
        reset_context(token)

    assert result["installed"] == 10
    assert result["skipped"] == 0
    assert len(rows) == 10
    for wf in rows:
        assert wf.status == WorkflowStatus.active
        assert wf.category == "Preset Workflow"
        assert wf.is_marketing is False
        assert wf.is_system_default is False


async def test_install_preset_workflows_is_idempotent(test_db, org_id):
    """A second call is a no-op: 0 installed, 10 skipped, still 10
    rows total. Guards against the backfill migration + the
    org-creation hook both firing for the same org."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()
        second = await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()

        count = (
            await test_db.execute(
                select(func.count()).select_from(Workflow).where(Workflow.org_id == org_id)
            )
        ).scalar_one()
    finally:
        reset_context(token)

    assert second["installed"] == 0
    assert second["skipped"] == 10
    assert count == 10


async def test_lead_confirmation_preserves_bulk_import_exclusion_condition(test_db, org_id):
    """The Lead Confirmation preset carries the same condition the
    old automation had — ``{"field": "source", "op": "ne", "value":
    "bulk_import"}`` — so bulk-CSV imports don't blast every imported
    contact with an auto-confirmation. This is a manager-locked
    default per the automation-engine Step 6 spec."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()

        wf = (
            await test_db.execute(
                select(Workflow).where(
                    Workflow.org_id == org_id,
                    Workflow.name == "Lead Confirmation",
                )
            )
        ).scalar_one()
    finally:
        reset_context(token)

    trigger_node = next(n for n in wf.graph["nodes"] if n["type"] == "trigger")
    conditions = trigger_node["config"]["conditions"]
    assert conditions == {"field": "source", "op": "ne", "value": "bulk_import"}


async def test_appointment_reminder_24h_uses_whatsapp_channel_and_phone_resolver(test_db, org_id):
    """The three appointment triggers historically went out on
    WhatsApp with the ``contact.phone`` resolver. Regression pin so a
    channel edit to the spec doesn't silently downgrade delivery."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()

        wf = (
            await test_db.execute(
                select(Workflow).where(
                    Workflow.org_id == org_id,
                    Workflow.name == "Appointment Reminder 24h",
                )
            )
        ).scalar_one()
    finally:
        reset_context(token)

    send_node = next(n for n in wf.graph["nodes"] if n["type"].startswith("send."))
    assert send_node["type"] == "send.whatsapp"
    assert send_node["config"]["recipient"] == "contact.phone"
    assert wf.enabled_event_types == ["appointment.reminder_24h"]


async def test_every_preset_send_node_carries_a_template_id(test_db, org_id):
    """The seed helper resolves ``template_id`` per spec via
    ``core.templates.seeds`` — every preset's send node must land with
    a populated template_id, otherwise the graph validator's DB-bound
    check rejects the workflow at activation time."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_preset_workflows(test_db, org_id=org_id)
        await test_db.commit()

        rows = list(
            (await test_db.execute(select(Workflow).where(Workflow.org_id == org_id))).scalars()
        )
    finally:
        reset_context(token)

    for wf in rows:
        send_nodes = [n for n in wf.graph["nodes"] if n["type"].startswith("send.")]
        assert send_nodes, f"workflow {wf.name!r} has no send node"
        for node in send_nodes:
            assert node["config"].get("template_id"), (
                f"workflow {wf.name!r} send node missing template_id"
            )


# ---------------------------------------------------------------------------
# Integration — org-creation hook wiring
# ---------------------------------------------------------------------------


async def test_create_organization_installs_preset_workflows_and_no_automations(test_db):
    """After the seed cutover, ``create_organization`` seeds preset
    workflows + zero automations. Guards against a regression that
    would re-wire the automation seed and cause duplicate-fire
    (workflow mirror + automation trigger both firing the same
    event)."""
    org = await create_organization(test_db, name="CutoverHookDemo")
    await test_db.commit()

    preset_count = (
        await test_db.execute(
            select(func.count())
            .select_from(Workflow)
            .where(
                Workflow.org_id == org.id,
                Workflow.category == "Preset Workflow",
            )
        )
    ).scalar_one()
    automation_count = (
        await test_db.execute(
            select(func.count())
            .select_from(AutomationTrigger)
            .where(AutomationTrigger.org_id == org.id)
        )
    ).scalar_one()

    assert preset_count == 10
    assert automation_count == 0
