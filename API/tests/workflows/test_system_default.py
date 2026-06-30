"""Pin tests for Step-21 system-default auto-active workflows.

Covers:

  * Seeder installs the 3 system-default catalog entries as
    ``status='active'`` and ``is_system_default=True``.
  * Non-flagged catalog entries still install as ``draft`` /
    ``is_system_default=False``.
  * ``archive_workflow`` refuses on system-default rows
    (raises :class:`WorkflowLocked`).
  * ``archive_workflow`` succeeds on regular rows.
  * ``create_organization`` provisions the org with system-defaults
    already active (the day-one safety net).
  * The Lead Auto-Triage seed graph has the expected structure (10
    nodes including the Slack hot-path side branch, lead.created
    trigger, goal node).
  * Catalog flag invariant: every ``auto_activate=True`` entry is
    also ``is_system_default=True`` (defence in depth — auto-active
    rows must always be protected).
  * Catalog flag invariant: every ``is_system_default=True`` entry
    has ``is_marketing=False`` (no contact-facing sends auto-active).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.tenants.service import create_organization
from src.app.core.workflows import service as workflows_service
from src.app.core.workflows import templates_gallery as wf_gallery
from src.app.core.workflows.exceptions import WorkflowLocked
from src.app.core.workflows.models import Workflow, WorkflowStatus
from src.app.core.workflows.seeds import install_seeded_workflows
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Catalog invariants
# ---------------------------------------------------------------------------


def test_auto_activate_entries_are_all_system_defaults():
    """Defence in depth — anything we install active is also protected
    from accidental archive. Prevents a future contributor from
    setting auto_activate=True without is_system_default=True."""
    for entry in wf_gallery.CATALOG:
        if entry.auto_activate:
            assert entry.is_system_default, (
                f"Catalog entry '{entry.name}' has auto_activate=True "
                "but is_system_default=False — auto-active rows must "
                "be protected from archive."
            )


def test_system_default_entries_are_internal_only():
    """System defaults install active immediately, so they must NOT
    have any contact-facing marketing sends. is_marketing=False is
    the manager's compliance guard."""
    for entry in wf_gallery.CATALOG:
        if entry.is_system_default:
            assert not entry.is_marketing, (
                f"Catalog entry '{entry.name}' is_system_default=True "
                "but is_marketing=True — contact-facing workflows "
                "cannot auto-activate."
            )


def test_exactly_three_system_defaults_in_catalog():
    """The day-one safety net is three workflows: Lead Auto-Triage,
    Deal Won Slack Alert, Daily Digest. Changing this count is a
    deliberate decision — the test flags drift."""
    defaults = [e for e in wf_gallery.CATALOG if e.is_system_default]
    assert len(defaults) == 3
    names = {e.name for e in defaults}
    assert names == {
        "New Lead Auto-Triage",
        "Deal Won Alert (Slack)",
        "Daily Digest to Sales Manager",
    }


# ---------------------------------------------------------------------------
# Lead Auto-Triage graph structure
# ---------------------------------------------------------------------------


def test_lead_auto_triage_graph_has_expected_structure():
    """Pin the 10-node intake graph so a refactor of
    `_lead_auto_triage_graph` can't silently drop required steps."""
    entry = next(
        e for e in wf_gallery.CATALOG if e.id == "lead.auto_triage"
    )
    graph = entry.graph_preview
    nodes_by_type: dict[str, int] = {}
    for node in graph["nodes"]:
        nodes_by_type[node["type"]] = nodes_by_type.get(node["type"], 0) + 1

    # Trigger.
    assert nodes_by_type.get("trigger") == 1
    # Two branch.switch nodes (source + score band).
    assert nodes_by_type.get("branch.switch") == 2
    # Routing assignment.
    assert nodes_by_type.get("routing.round_robin") == 1
    # Stamp lead + sync contact.
    assert nodes_by_type.get("record.update_lead_field") == 1
    assert nodes_by_type.get("record.update_contact_field") == 1
    # Tag, notify, task.
    assert nodes_by_type.get("tagging.add_tag") == 1
    assert nodes_by_type.get("flow_control.notify_user") == 1
    assert nodes_by_type.get("record.create_task") == 1
    # Slack hot-path send + two goals (main + slack).
    assert nodes_by_type.get("send.slack") == 1
    assert nodes_by_type.get("flow_control.goal") == 2

    # Trigger fires on lead.created.
    trigger = next(n for n in graph["nodes"] if n["type"] == "trigger")
    assert trigger["config"]["event_type"] == "lead.created"


# ---------------------------------------------------------------------------
# Seeder behaviour
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "SysDefDemo",
            "slug": f"sysdef-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _list_workflows(test_db, org_id):
    return list(
        (
            await test_db.execute(
                select(Workflow).where(Workflow.org_id == org_id)
            )
        ).scalars()
    )


async def test_system_defaults_install_active(test_db, org_id):
    """The 3 system-default seeds install with status='active' and
    is_system_default=True."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    sys_defaults = [w for w in rows if w.is_system_default]
    assert len(sys_defaults) == 3
    for wf in sys_defaults:
        assert wf.status == WorkflowStatus.active, (
            f"{wf.name} should install active but is {wf.status.value}"
        )


async def test_non_system_seeds_still_install_as_drafts(test_db, org_id):
    """Catalog entries without the flags continue to install as
    draft + is_system_default=False (the Step-20 contract)."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
    finally:
        reset_context(token)

    non_defaults = [w for w in rows if not w.is_system_default]
    assert len(non_defaults) > 0
    for wf in non_defaults:
        assert wf.status == WorkflowStatus.draft, (
            f"{wf.name} should install draft but is {wf.status.value}"
        )


# ---------------------------------------------------------------------------
# Service guards
# ---------------------------------------------------------------------------


async def test_archive_refuses_on_system_default(test_db, org_id):
    """``archive_workflow`` raises :class:`WorkflowLocked` when the
    target is a system-default row."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
        sys_default = next(w for w in rows if w.is_system_default)

        with pytest.raises(WorkflowLocked):
            await workflows_service.archive_workflow(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=sys_default.id,
            )
    finally:
        reset_context(token)


async def test_archive_succeeds_on_regular_workflow(test_db, org_id):
    """``archive_workflow`` works normally on non-system-default rows."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await install_seeded_workflows(test_db, org_id=org_id)
        await test_db.commit()
        rows = await _list_workflows(test_db, org_id)
        regular = next(w for w in rows if not w.is_system_default)

        result = await workflows_service.archive_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=regular.id,
        )
        assert result.status == WorkflowStatus.archived
    finally:
        reset_context(token)


# ---------------------------------------------------------------------------
# Org provisioning hook
# ---------------------------------------------------------------------------


async def test_create_organization_provisions_system_defaults_active(test_db):
    """A brand new org boots into a functioning CRM — the 3 system
    defaults are already active without any operator setup."""
    org = await create_organization(test_db, name="DayOneCRM")
    await test_db.commit()
    rows = await _list_workflows(test_db, org.id)
    sys_defaults = [w for w in rows if w.is_system_default]
    assert len(sys_defaults) == 3
    assert all(w.status == WorkflowStatus.active for w in sys_defaults)
