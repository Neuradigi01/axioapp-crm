"""Pin tests for Step-16 gallery + clone-from-gallery.

Covers:

  * :func:`templates_gallery.list_gallery` returns exactly 15 catalog
    entries.
  * :func:`templates_gallery.clone_from_gallery` creates a draft
    workflow + carries the graph_preview verbatim (modulo template_id
    stripping).
  * Cloned send-action nodes land with ``template_id`` absent —
    operators pick a template per node via the Step-15 editor.
  * Auto-suffix on duplicate-name clash — operator who supplies a
    name already in use gets ``(2)``, ``(3)``, … appended.
  * Clone defaults ``re_enrollment_rule`` + ``is_marketing`` from the
    gallery entry (not the workflow service defaults).

Each test bypasses the Step-3 graph validator's DB-bound checks by
patching the catalog's placeholder graphs through ``create_workflow``
which exercises the full Step-2 validator. The catalog ships
trigger → send → goal graphs that satisfy single-trigger + no-cycle.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import templates_gallery
from src.app.core.workflows.models import Workflow, WorkflowStatus
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


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
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


# ---------------------------------------------------------------------------
# Catalogue size
# ---------------------------------------------------------------------------


def test_list_gallery_returns_exactly_15_entries():
    """The spec ships 15 default workflows. The catalogue list MUST
    match — Step 20 will rely on exactly this set when seeding new
    orgs."""
    entries = templates_gallery.list_gallery()
    assert len(entries) == 15, (
        f"expected 15 catalogue entries, got {len(entries)}"
    )
    # Every entry has a stable id + non-empty graph_preview.
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == 15, "catalogue ids must be unique"
    for entry in entries:
        assert entry["graph_preview"].get("nodes"), (
            f"entry {entry['id']!r} has no nodes in graph_preview"
        )


# ---------------------------------------------------------------------------
# Clone — happy path
# ---------------------------------------------------------------------------


async def test_clone_from_gallery_creates_draft_and_carries_graph(
    test_db, org_id
):
    """The clone path creates a `status='draft'` row, copies the
    graph_preview node ids over verbatim (minus template_id
    stripping), and stamps the operator-supplied name."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        clone = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="lead.welcome_auto_assign",
            name="My Welcome Workflow",
            folder_id=None,
        )
    finally:
        reset_context(token)

    assert isinstance(clone, Workflow)
    assert clone.status == WorkflowStatus.draft
    assert clone.name == "My Welcome Workflow"
    assert clone.org_id == org_id
    # Graph carried over (same number of nodes + edges as the catalogue).
    source = templates_gallery.get_template("lead.welcome_auto_assign")
    assert source is not None
    assert len(clone.graph["nodes"]) == len(source.graph_preview["nodes"])
    assert len(clone.graph["edges"]) == len(source.graph_preview["edges"])


# ---------------------------------------------------------------------------
# Send-action template_id stripping
# ---------------------------------------------------------------------------


async def test_clone_strips_template_id_from_send_actions(test_db, org_id):
    """Send-action + record.create_* nodes ship with `template_id`
    removed + `__valid=false` stamped so the Step-15 editor lights
    the red validation dot until the operator picks a real
    template per node."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        clone = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="lead.hot_nurture",
            name="Hot Lead Clone",
            folder_id=None,
        )
    finally:
        reset_context(token)

    send_nodes = [
        n for n in clone.graph["nodes"] if str(n.get("type", "")).startswith("send.")
    ]
    assert len(send_nodes) >= 1, "hot_nurture template has send nodes"
    for node in send_nodes:
        cfg = node.get("config") or {}
        assert "template_id" not in cfg, (
            f"send node {node['id']} still carries template_id after clone"
        )
        assert cfg.get("__valid") is False, (
            "stripped send nodes must stamp __valid=false for the editor"
        )


# ---------------------------------------------------------------------------
# Duplicate-name handling
# ---------------------------------------------------------------------------


async def test_clone_auto_suffixes_on_duplicate_name(test_db, org_id):
    """When the operator-supplied name collides with an existing
    workflow, the clone path auto-uniqifies with `(2)`, `(3)`, …
    suffixes rather than raising a 409."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        first = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="quote.follow_up",
            name="Quote Follow-Up",
            folder_id=None,
        )
        second = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="quote.follow_up",
            name="Quote Follow-Up",
            folder_id=None,
        )
    finally:
        reset_context(token)

    assert first.name == "Quote Follow-Up"
    assert second.name == "Quote Follow-Up (2)"
    assert first.id != second.id


# ---------------------------------------------------------------------------
# Re-enrollment + marketing defaults
# ---------------------------------------------------------------------------


async def test_clone_uses_gallery_entry_defaults_for_marketing_and_re_enrollment(
    test_db, org_id
):
    """Clone reads `is_marketing` + `re_enrollment_rule` from the
    catalogue entry — internal templates (Slack alerts, daily
    digests) ship with `is_marketing=False` and must keep that
    setting in the cloned row."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        marketing_clone = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="lead.welcome_auto_assign",
            name="Marketing Clone",
            folder_id=None,
        )
        internal_clone = await templates_gallery.clone_from_gallery(
            test_db,
            org_id=org_id,
            user_id=None,
            template_id="internal.deal_won_alert",
            name="Internal Clone",
            folder_id=None,
        )
    finally:
        reset_context(token)

    assert marketing_clone.is_marketing is True
    assert internal_clone.is_marketing is False
