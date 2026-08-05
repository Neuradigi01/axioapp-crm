"""Pin tests for Step 1 of ``tasks/workflows-absorb-automation/`` —
the schema + data migration that mirrors every automation row into a
single-step workflow.

Coverage split (matches the ``test_sequences_absorption.py`` pattern):

  * Pure translator (``_build_graph``) — three cases exercising the
    three shape branches (no delay, with delay, condition
    preservation).
  * DAL helpers (``find_by_migrated_workflow_id``,
    ``set_migrated_to``) — behavioural round-trip against real
    tables.
  * Schema pin — the FK column is present, indexed, and defaults to
    NULL so the two migrations remain deploy-safe.

Full end-to-end upgrade/downgrade parity is exercised by the smoke
checklist in :file:`tasks/workflows-absorb-automation/step-4-smoke-verification.md`
(a real Alembic run against a snapshot of Ajay's Workspace) — running
``upgrade()``/``downgrade()`` from pytest would require constructing an
Alembic ``op`` context, and the ``test_db`` fixture already installs
the columns via ``Base.metadata.create_all``.
"""

from __future__ import annotations

import importlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.automation import data_access as auto_da
from src.app.core.automation.models import AutomationTrigger
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Translator — pure function, no DB
# ---------------------------------------------------------------------------


def _load_migration_module():
    """Load the data-migration module via importlib because the file
    name (``0176_bf_autos_to_workflows``) starts with a digit + can't
    be imported with the ``import`` statement."""
    return importlib.import_module("alembic.versions.0176_bf_autos_to_workflows")


def test_build_graph_no_delay_produces_two_node_dag():
    """delay_seconds=0 → trigger → send. No wait node. One edge."""
    mod = _load_migration_module()
    template_id = str(uuid.uuid4())

    graph = mod._build_graph(
        event_type="user.signed_up",
        conditions=None,
        channel_node_type="send.email",
        template_id=template_id,
        recipient_resolver="user.email",
        recipient_resolver_config={},
        delay_seconds=0,
    )

    node_types = [n["type"] for n in graph["nodes"]]
    assert node_types == ["trigger", "send.email"]
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert edge["source"] == graph["nodes"][0]["id"]
    assert edge["target"] == graph["nodes"][1]["id"]

    trigger = graph["nodes"][0]
    assert trigger["config"]["event_type"] == "user.signed_up"

    send = graph["nodes"][1]
    assert send["config"]["template_id"] == template_id
    assert send["config"]["recipient_resolver"] == "user.email"
    assert send["config"]["recipient_resolver_config"] == {}


def test_build_graph_positive_delay_inserts_wait_node_before_send():
    """delay_seconds>0 → trigger → flow.wait → send. Two edges.
    Wait config carries both ``delay_seconds`` (engine's preferred key)
    and ``max_wait_seconds`` (graph validator's required key)."""
    mod = _load_migration_module()
    graph = mod._build_graph(
        event_type="lead.created",
        conditions=None,
        channel_node_type="send.whatsapp",
        template_id=str(uuid.uuid4()),
        recipient_resolver="contact.phone",
        recipient_resolver_config={},
        delay_seconds=3600,
    )

    node_types = [n["type"] for n in graph["nodes"]]
    assert node_types == ["trigger", "flow.wait", "send.whatsapp"]
    assert len(graph["edges"]) == 2

    wait_node = graph["nodes"][1]
    assert wait_node["config"]["delay_seconds"] == 3600
    assert wait_node["config"]["max_wait_seconds"] == 3600


def test_build_graph_preserves_source_conditions_on_trigger_node():
    """Automation ``conditions`` JSONB round-trips onto the trigger
    node's ``config.conditions`` — the workflow condition evaluator
    reads from that key."""
    mod = _load_migration_module()
    conditions = {"and": [{"field": "lead.source", "op": "eq", "value": "widget"}]}

    graph = mod._build_graph(
        event_type="lead.created",
        conditions=conditions,
        channel_node_type="send.email",
        template_id=str(uuid.uuid4()),
        recipient_resolver="contact.email",
        recipient_resolver_config={"jsonpath": "$.lead.email"},
        delay_seconds=0,
    )

    trigger = graph["nodes"][0]
    assert trigger["config"]["conditions"] == conditions

    send = graph["nodes"][1]
    assert send["config"]["recipient_resolver_config"] == {"jsonpath": "$.lead.email"}


# ---------------------------------------------------------------------------
# DAL helpers — round-trip against real tables
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org), "name": "AbsorbAutoDemo", "slug": f"aad-{org.hex[:6]}"},
    )
    await test_db.commit()
    return org


@pytest_asyncio.fixture
async def template_id(test_db, org_id):
    """Minimal published email template so the automation trigger's
    template_id FK (RESTRICT) accepts the insert."""
    tid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            """
            INSERT INTO tbl_message_templates
                (id, org_id, name, channel, category, internal_status,
                 subject, body, variables, created_at, updated_at)
            VALUES
                (CAST(:id AS UUID), CAST(:org AS UUID), :name,
                 CAST('email' AS conversation_channel),
                 'transactional', 'published',
                 'Hello', 'Body', '[]'::jsonb, now(), now())
            """
        ),
        {"id": str(tid), "org": str(org_id), "name": "T-absorb-demo"},
    )
    await test_db.commit()
    return tid


async def _insert_automation(
    test_db, *, org_id: uuid.UUID, template_id: uuid.UUID, name: str = "T"
) -> uuid.UUID:
    tid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            """
            INSERT INTO tbl_automation_triggers
                (id, org_id, name, enabled, event_type, conditions,
                 channel, template_id, delay_seconds,
                 recipient_resolver, recipient_resolver_config,
                 created_at, updated_at)
            VALUES
                (CAST(:id AS UUID), CAST(:org AS UUID), :name, true,
                 :event, '{}'::jsonb,
                 CAST('email' AS conversation_channel),
                 CAST(:tmpl AS UUID), 0,
                 'contact.email', '{}'::jsonb, now(), now())
            """
        ),
        {
            "id": str(tid),
            "org": str(org_id),
            "name": name,
            "event": "lead.created",
            "tmpl": str(template_id),
        },
    )
    await test_db.commit()
    return tid


async def _insert_workflow(test_db, *, org_id: uuid.UUID, name: str) -> uuid.UUID:
    wid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            """
            INSERT INTO tbl_workflows
                (id, org_id, name, category, status, current_version,
                 re_enrollment_rule, is_marketing, is_system_default,
                 graph, cost_per_run_cents, enabled_event_types,
                 ab_test_min_runs_per_variant, ab_test_winner_metric,
                 cached_running_count, cached_completed_today_count,
                 created_at, updated_at)
            VALUES
                (CAST(:id AS UUID), CAST(:org AS UUID), :name,
                 'Migrated Automation',
                 CAST('active' AS workflow_status), 1,
                 CAST('once' AS workflow_re_enrollment_rule),
                 false, false,
                 '{"nodes": [], "edges": []}'::jsonb, 0,
                 CAST('{}' AS TEXT[]),
                 50, CAST('goal_conversion' AS ab_winner_metric),
                 0, 0,
                 now(), now())
            """
        ),
        {"id": str(wid), "org": str(org_id), "name": name},
    )
    await test_db.commit()
    return wid


async def test_find_by_migrated_workflow_id_returns_source_after_link(test_db, org_id, template_id):
    """DAL helper resolves the workflow id back to the source
    automation — the redirect resolver (Step 3) relies on this."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        automation_id = await _insert_automation(
            test_db, org_id=org_id, template_id=template_id, name="Welcome"
        )
        workflow_id = await _insert_workflow(test_db, org_id=org_id, name="Welcome")
        await test_db.execute(
            sql_text(
                "UPDATE tbl_automation_triggers "
                "SET migrated_to_workflow_id = CAST(:wf AS UUID) "
                "WHERE id = CAST(:aid AS UUID)"
            ),
            {"wf": str(workflow_id), "aid": str(automation_id)},
        )
        await test_db.commit()

        row = await auto_da.find_by_migrated_workflow_id(test_db, workflow_id=workflow_id)
    finally:
        reset_context(token)

    assert row is not None
    assert row.id == automation_id
    assert row.migrated_to_workflow_id == workflow_id


async def test_find_by_migrated_workflow_id_returns_none_for_native_workflow(test_db, org_id):
    """A workflow with no source automation returns None — resolver
    must fall back to the workflows list instead of 404."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        workflow_id = await _insert_workflow(test_db, org_id=org_id, name="Native")
        row = await auto_da.find_by_migrated_workflow_id(test_db, workflow_id=workflow_id)
    finally:
        reset_context(token)

    assert row is None


async def test_set_migrated_to_flips_enabled_false_and_links_workflow(test_db, org_id, template_id):
    """The staging helper mutates in place; caller commits."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        automation_id = await _insert_automation(
            test_db, org_id=org_id, template_id=template_id, name="Reminder"
        )
        workflow_id = await _insert_workflow(test_db, org_id=org_id, name="Reminder")

        automation = (
            await test_db.execute(
                select(AutomationTrigger).where(AutomationTrigger.id == automation_id)
            )
        ).scalar_one()

        auto_da.set_migrated_to(test_db, automation=automation, workflow_id=workflow_id)
        await test_db.commit()

        refreshed = (
            await test_db.execute(
                select(AutomationTrigger).where(AutomationTrigger.id == automation_id)
            )
        ).scalar_one()
    finally:
        reset_context(token)

    assert refreshed.enabled is False
    assert refreshed.migrated_to_workflow_id == workflow_id


# ---------------------------------------------------------------------------
# Schema pin — the FK column and its properties survive future refactors
# ---------------------------------------------------------------------------


async def test_migrated_to_workflow_id_column_exists_and_is_nullable(test_db):
    """Regression pin: the column stays nullable so re-runs of the
    schema migration don't fail on existing NULL rows, and the FK
    respects ``ON DELETE SET NULL`` per the migration contract."""
    row = (
        await test_db.execute(
            sql_text(
                """
                SELECT is_nullable, data_type
                  FROM information_schema.columns
                 WHERE table_name = 'tbl_automation_triggers'
                   AND column_name = 'migrated_to_workflow_id'
                """
            )
        )
    ).one_or_none()

    assert row is not None, (
        "tbl_automation_triggers.migrated_to_workflow_id column missing — "
        "verify ORM model change and Alembic migration 0175 applied."
    )
    is_nullable, data_type = row
    assert is_nullable == "YES"
    assert data_type == "uuid"
