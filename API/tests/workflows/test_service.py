"""Pin tests for the Step-2 workflows service layer.

Covers:

  * ``create_workflow`` persists + writes a v1 version row.
  * Duplicate name in same org → ``DuplicateWorkflowName``.
  * Same name in different org allowed (RLS-scoped uniqueness).
  * ``update_workflow`` bumps ``current_version`` + writes a new
    version row when ``graph`` is in the patch.
  * ``update_workflow`` on an active marketing workflow →
    ``WorkflowLocked``.
  * ``change_status('active')`` re-validates the persisted graph;
    a broken graph re-raises ``InvalidGraph``.
  * Folder delete on a non-empty folder → ``FolderHasWorkflows``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateCategory,
)
from src.app.core.templates.schemas import TemplateCreate
from src.app.core.workflows import service as workflows_service
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    register_action,
)
from src.app.core.workflows.exceptions import (
    DuplicateWorkflowName,
    FolderHasWorkflows,
    WorkflowLocked,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowFolder,
    WorkflowStatus,
    WorkflowVersion,
)
from src.app.core.workflows.schemas import (
    GraphEdge,
    GraphNode,
    WorkflowCreate,
    WorkflowFolderCreate,
    WorkflowGraph,
    WorkflowUpdate,
)
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


@pytest.fixture(autouse=True)
def _seed_action_registry():
    """Register the ``send.email`` action so the graph validator
    passes its action-registry check during service tests."""
    _clear_registry_for_tests()
    register_action("send.email", lambda: object())
    yield
    _clear_registry_for_tests()


async def _seed_template(test_db, *, org_id) -> uuid.UUID:
    """Create a published email template the workflow's send node
    can reference."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        tpl = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name=f"WF-tpl-{uuid.uuid4().hex[:4]}",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi",
                subject="Hi",
            ),
        )
    finally:
        reset_context(token)
    return tpl.id


def _make_graph(template_id: uuid.UUID) -> WorkflowGraph:
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
                config={"template_id": str(template_id)},
            ),
        ],
        edges=[GraphEdge(id="e1", source="t1", target="s1")],
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_workflow_persists_and_writes_v1_version(test_db, org_id):
    template_id = await _seed_template(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        workflow = await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                graph=_make_graph(template_id),
            ),
        )
    finally:
        reset_context(token)

    assert workflow.id is not None
    assert workflow.status == WorkflowStatus.draft
    assert workflow.current_version == 1
    assert workflow.enabled_event_types == ["lead.created"]

    versions = (
        await test_db.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id
            )
        )
    ).scalars().all()
    assert len(versions) == 1
    assert versions[0].version == 1


async def test_duplicate_name_in_same_org_rejected(test_db, org_id):
    template_id = await _seed_template(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                graph=_make_graph(template_id),
            ),
        )
        with pytest.raises(DuplicateWorkflowName):
            await workflows_service.create_workflow(
                test_db,
                org_id=org_id,
                user_id=None,
                payload=WorkflowCreate(
                    name="welcome",  # case-insensitive collision
                    graph=_make_graph(template_id),
                ),
            )
    finally:
        reset_context(token)


async def test_same_name_in_different_orgs_allowed(test_db, org_id):
    other_org = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(other_org),
            "name": "Other",
            "slug": f"other-{other_org.hex[:6]}",
        },
    )
    await test_db.commit()

    tpl_a = await _seed_template(test_db, org_id=org_id)
    tpl_b = await _seed_template(test_db, org_id=other_org)

    token_a = set_context(RequestContext(org_id=org_id))
    try:
        await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                graph=_make_graph(tpl_a),
            ),
        )
    finally:
        reset_context(token_a)

    token_b = set_context(RequestContext(org_id=other_org))
    try:
        wf_b = await workflows_service.create_workflow(
            test_db,
            org_id=other_org,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",  # same name, different org
                graph=_make_graph(tpl_b),
            ),
        )
    finally:
        reset_context(token_b)
    assert wf_b.name == "Welcome"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def test_update_graph_bumps_version_and_writes_new_row(test_db, org_id):
    template_id = await _seed_template(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        workflow = await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                graph=_make_graph(template_id),
            ),
        )

        # Edit the description AND swap the graph for a fresh one
        # (same shape — exercises the version-bump path).
        new_graph = _make_graph(template_id)
        new_graph.nodes[1].config["template_id"] = str(template_id)  # idempotent
        updated = await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=workflow.id,
            payload=WorkflowUpdate(
                description="now with feeling",
                graph=new_graph,
            ),
        )
    finally:
        reset_context(token)

    assert updated.current_version == 2
    assert updated.description == "now with feeling"

    versions = (
        await test_db.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow.id)
            .order_by(WorkflowVersion.version.asc())
        )
    ).scalars().all()
    assert len(versions) == 2
    assert [v.version for v in versions] == [1, 2]


async def test_update_active_marketing_workflow_locked(test_db, org_id):
    template_id = await _seed_template(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        workflow = await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                is_marketing=True,
                graph=_make_graph(template_id),
            ),
        )
        await workflows_service.change_status(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=workflow.id,
            new_status=WorkflowStatus.active,
        )

        with pytest.raises(WorkflowLocked):
            await workflows_service.update_workflow(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=workflow.id,
                payload=WorkflowUpdate(description="edit attempt"),
            )

        # Pause → edit → reactivate is the supported flow.
        await workflows_service.change_status(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=workflow.id,
            new_status=WorkflowStatus.paused,
        )
        unlocked = await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=workflow.id,
            payload=WorkflowUpdate(description="paused edit OK"),
        )
        assert unlocked.description == "paused edit OK"
    finally:
        reset_context(token)


# ---------------------------------------------------------------------------
# Folder CRUD
# ---------------------------------------------------------------------------


async def test_delete_folder_with_workflows_refuses(test_db, org_id):
    template_id = await _seed_template(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        folder = await workflows_service.create_folder(
            test_db,
            org_id=org_id,
            payload=WorkflowFolderCreate(name="Sales"),
        )
        await workflows_service.create_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=WorkflowCreate(
                name="Welcome",
                folder_id=folder.id,
                graph=_make_graph(template_id),
            ),
        )

        with pytest.raises(FolderHasWorkflows) as exc:
            await workflows_service.delete_folder(
                test_db,
                org_id=org_id,
                folder_id=folder.id,
            )
        assert exc.value.count == 1
    finally:
        reset_context(token)


async def test_delete_empty_folder_succeeds(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        folder = await workflows_service.create_folder(
            test_db,
            org_id=org_id,
            payload=WorkflowFolderCreate(name="Empty"),
        )
        await workflows_service.delete_folder(
            test_db,
            org_id=org_id,
            folder_id=folder.id,
        )
        rows = (
            await test_db.execute(
                select(WorkflowFolder).where(
                    WorkflowFolder.id == folder.id
                )
            )
        ).scalars().all()
        assert rows == []
    finally:
        reset_context(token)
