"""Service layer for the workflows module.

Owns all workflow + folder business logic. Only layer that touches
transactions (manager spec 2026-06-25); DAL stays read-only with
no commits.

Lifecycle invariants enforced here:

  * Status transitions follow the documented state machine
    (``draft → active``, ``active ↔ paused``, anything →
    ``archived``).
  * Activating a workflow re-runs the graph validator so a draft
    can't go live broken.
  * Editing a ``status='active'`` AND ``is_marketing=true``
    workflow is refused (:class:`WorkflowLocked`). Operator
    pauses → edits → reactivates. Outstanding runs continue
    under the old version row in ``tbl_workflow_versions``
    (immutable history).
  * Every publish (create + every update with a graph change)
    writes a new row in ``tbl_workflow_versions`` so Step 17 can
    diff / revert.
  * Folder deletion refuses on non-empty folders
    (:class:`FolderHasWorkflows`) — operator reassigns first.

Compliance pre-flight (Step 12) hooks in via the ``ActivationBlocked``
exception path. Until Step 12 lands the hook is a no-op.
"""
from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import data_access as _da
from src.app.core.workflows.exceptions import (
    DuplicateWorkflowName,
    FolderHasWorkflows,
    InvalidGraph,
    WorkflowLocked,
    WorkflowNotFound,
)
from src.app.core.workflows.graph import validate_graph_with_db
from src.app.core.workflows.models import (
    Workflow,
    WorkflowFolder,
    WorkflowReEnrollmentRule,
    WorkflowStatus,
    WorkflowVersion,
)
from src.app.core.workflows.schemas import (
    WorkflowCreate,
    WorkflowFolderCreate,
    WorkflowGraph,
    WorkflowUpdate,
)


# Status transitions the service allows. Any transition not in
# this set raises a :class:`ValueError` — the router maps to 409.
_ALLOWED_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.draft: frozenset(
        {WorkflowStatus.active, WorkflowStatus.archived}
    ),
    WorkflowStatus.active: frozenset(
        {WorkflowStatus.paused, WorkflowStatus.archived}
    ),
    WorkflowStatus.paused: frozenset(
        {WorkflowStatus.active, WorkflowStatus.archived}
    ),
    WorkflowStatus.archived: frozenset(),
}


def _extract_event_types(graph: WorkflowGraph) -> list[str]:
    """Pull the denormalised ``enabled_event_types`` list from the
    graph's trigger node(s). Step-5 matcher reads this via the
    GIN index on ``tbl_workflows.enabled_event_types``."""
    out: list[str] = []
    for n in graph.nodes:
        if (n.type or "").startswith("trigger"):
            et = (n.config or {}).get("event_type")
            if isinstance(et, str) and et.strip() and et not in out:
                out.append(et.strip())
    return out


def _is_marketing_locked(workflow: Workflow) -> bool:
    """Active marketing workflows lock against edits. Operator
    pauses + edits + reactivates so an in-flight enrolment doesn't
    switch graph mid-stream."""
    return bool(
        workflow.status == WorkflowStatus.active and workflow.is_marketing
    )


# --- workflow CRUD ------------------------------------------------------


async def create_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: WorkflowCreate,
) -> Workflow:
    """Create a new workflow in ``status='draft'``. Validates the
    graph (structural + DB-bound) and writes a v1 row in
    ``tbl_workflow_versions`` so Step 17 has a starting baseline.
    Raises :class:`DuplicateWorkflowName` when ``(org_id, lower(name))``
    is taken."""
    existing = await _da.get_workflow_by_name(
        session, org_id=org_id, name=payload.name
    )
    if existing is not None:
        raise DuplicateWorkflowName(
            f"workflow named '{payload.name}' already exists"
        )

    # DB-bound validation: template-id references resolve, action
    # types resolve, no cycles, single trigger, etc.
    await validate_graph_with_db(
        session,
        org_id=org_id,
        graph=payload.graph,
        goal_node_id=payload.goal_node_id,
    )

    workflow = Workflow(
        org_id=org_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        folder_id=payload.folder_id,
        status=WorkflowStatus.draft,
        current_version=1,
        re_enrollment_rule=WorkflowReEnrollmentRule(payload.re_enrollment_rule),
        is_marketing=payload.is_marketing,
        graph=payload.graph.model_dump(),
        goal_node_id=payload.goal_node_id,
        cost_per_run_cents=payload.cost_per_run_cents,
        enabled_event_types=_extract_event_types(payload.graph),
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    _da.add_workflow(session, workflow)
    await session.flush()

    version = WorkflowVersion(
        org_id=org_id,
        workflow_id=workflow.id,
        version=1,
        graph=payload.graph.model_dump(),
        change_note="initial version",
        created_by_user_id=user_id,
    )
    _da.add_version(session, version)
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def get_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> Workflow:
    """Single-row hydrate. Raises :class:`WorkflowNotFound` on miss."""
    row = await _da.get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    if row is None:
        raise WorkflowNotFound(str(workflow_id))
    return row


async def list_workflows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: WorkflowStatus | None = None,
    category: str | None = None,
    folder_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Workflow], int]:
    """Passthrough to the DAL. Pagination + filters happen in SQL
    so the operator's tens-of-thousands-of-workflows org doesn't
    page everything into memory."""
    return await _da.list_workflows(
        session,
        org_id=org_id,
        status=status,
        category=category,
        folder_id=folder_id,
        q=q,
        limit=limit,
        offset=offset,
    )


async def update_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
) -> Workflow:
    """PATCH a workflow. Active marketing workflows are locked
    (:class:`WorkflowLocked`); operator pauses + edits +
    reactivates. Any graph change bumps ``current_version`` and
    writes a new row in ``tbl_workflow_versions``."""
    workflow = await get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    if _is_marketing_locked(workflow):
        raise WorkflowLocked(
            "cannot edit an active marketing workflow; pause it first"
        )

    changes = payload.model_dump(exclude_unset=True)

    # Name uniqueness re-check when renaming.
    new_name = changes.get("name")
    if new_name is not None and new_name.strip().lower() != workflow.name.lower():
        clash = await _da.get_workflow_by_name(
            session, org_id=org_id, name=new_name
        )
        if clash is not None and clash.id != workflow.id:
            raise DuplicateWorkflowName(
                f"workflow named '{new_name}' already exists"
            )

    # Graph re-validation when supplied.
    new_graph_obj: WorkflowGraph | None = None
    if "graph" in changes and changes["graph"] is not None:
        if isinstance(payload.graph, WorkflowGraph):
            new_graph_obj = payload.graph
        else:
            new_graph_obj = WorkflowGraph.model_validate(changes["graph"])
        goal = changes.get("goal_node_id", workflow.goal_node_id)
        await validate_graph_with_db(
            session,
            org_id=org_id,
            graph=new_graph_obj,
            goal_node_id=goal,
        )

    # Apply scalar fields.
    for key in (
        "name",
        "description",
        "category",
        "folder_id",
        "is_marketing",
        "goal_node_id",
        "cost_per_run_cents",
    ):
        if key in changes and changes[key] is not None:
            setattr(workflow, key, changes[key])

    if "re_enrollment_rule" in changes and changes["re_enrollment_rule"] is not None:
        workflow.re_enrollment_rule = WorkflowReEnrollmentRule(
            changes["re_enrollment_rule"]
        )

    # Status changes go through ``change_status`` so the state
    # machine is enforced consistently.
    if "status" in changes and changes["status"] is not None:
        new_status = WorkflowStatus(changes["status"])
        if new_status != workflow.status:
            await _transition_status_in_session(
                session,
                workflow=workflow,
                org_id=org_id,
                new_status=new_status,
            )

    if new_graph_obj is not None:
        workflow.graph = new_graph_obj.model_dump()
        workflow.enabled_event_types = _extract_event_types(new_graph_obj)
        workflow.current_version = workflow.current_version + 1
        version = WorkflowVersion(
            org_id=org_id,
            workflow_id=workflow.id,
            version=workflow.current_version,
            graph=workflow.graph,
            change_note=changes.get("change_note"),
            created_by_user_id=user_id,
        )
        _da.add_version(session, version)

    workflow.updated_by_user_id = user_id
    await session.commit()
    await session.refresh(workflow)
    return workflow


# --- status transitions -------------------------------------------------


async def change_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    new_status: WorkflowStatus | Literal["draft", "active", "paused", "archived"],
) -> Workflow:
    """Lifecycle transition. Activation re-validates the graph so
    a broken draft can't go live; arbitrary states can always
    archive (no edits allowed after).

    Raises:
      * :class:`InvalidGraph` — activation refused because the
        graph is broken.
      * :class:`ValueError` — invalid transition (router maps to
        409).
    """
    workflow = await get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    target = (
        new_status
        if isinstance(new_status, WorkflowStatus)
        else WorkflowStatus(new_status)
    )
    await _transition_status_in_session(
        session, workflow=workflow, org_id=org_id, new_status=target
    )
    workflow.updated_by_user_id = user_id
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def _transition_status_in_session(
    session: AsyncSession,
    *,
    workflow: Workflow,
    org_id: uuid.UUID,
    new_status: WorkflowStatus,
) -> None:
    """Mutate ``workflow.status`` in-place + run the activation
    pre-flight. Does NOT commit — the caller orchestrates the
    transaction so multi-field updates land atomically."""
    if new_status == workflow.status:
        return

    allowed = _ALLOWED_TRANSITIONS.get(workflow.status, frozenset())
    if new_status not in allowed:
        raise ValueError(
            f"invalid status transition {workflow.status.value!r} → "
            f"{new_status.value!r}"
        )

    if new_status == WorkflowStatus.active:
        # Re-run the validator against the persisted graph so a
        # workflow whose graph was edited externally (via SQL) can't
        # sneak past the structural checks.
        await validate_graph_with_db(
            session,
            org_id=org_id,
            graph=WorkflowGraph.model_validate(workflow.graph),
            goal_node_id=workflow.goal_node_id,
        )

    workflow.status = new_status


async def archive_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
) -> Workflow:
    """Soft archive — flips status to ``archived`` so outstanding
    runs continue under the archived version (immutable history)."""
    return await change_status(
        session,
        org_id=org_id,
        user_id=user_id,
        workflow_id=workflow_id,
        new_status=WorkflowStatus.archived,
    )


# --- folder CRUD --------------------------------------------------------


async def create_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: WorkflowFolderCreate,
) -> WorkflowFolder:
    folder = WorkflowFolder(
        org_id=org_id,
        name=payload.name,
        parent_folder_id=payload.parent_folder_id,
        display_order=payload.display_order,
    )
    _da.add_folder(session, folder)
    await session.commit()
    await session.refresh(folder)
    return folder


async def list_folders(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[WorkflowFolder]:
    return await _da.list_folders(session, org_id=org_id)


async def patch_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    folder_id: uuid.UUID,
    name: str | None = None,
    parent_folder_id: uuid.UUID | None = None,
    display_order: int | None = None,
) -> WorkflowFolder:
    folder = await _da.get_folder(
        session, org_id=org_id, folder_id=folder_id
    )
    if folder is None:
        raise WorkflowNotFound(str(folder_id))
    if name is not None:
        folder.name = name
    if parent_folder_id is not None:
        folder.parent_folder_id = parent_folder_id
    if display_order is not None:
        folder.display_order = display_order
    await session.commit()
    await session.refresh(folder)
    return folder


async def delete_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> None:
    """Hard delete. Refuses with :class:`FolderHasWorkflows` when
    the folder still has non-archived workflows assigned."""
    folder = await _da.get_folder(
        session, org_id=org_id, folder_id=folder_id
    )
    if folder is None:
        raise WorkflowNotFound(str(folder_id))
    blocking_count = await _da.count_workflows_in_folder(
        session, org_id=org_id, folder_id=folder_id
    )
    if blocking_count > 0:
        raise FolderHasWorkflows(blocking_count)
    await _da.delete_folder(session, folder)
    await session.commit()


async def update_enabled_event_types_from_graph(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> list[str]:
    """Re-read the workflow's graph + rewrite
    ``tbl_workflows.enabled_event_types`` so the Step-5 matcher's
    ``ANY(enabled_event_types)`` filter stays in sync with the
    actual trigger nodes in the JSONB graph.

    Called by :func:`update_workflow` (Step 2 extended in Step 5)
    so every save propagates the change. The hook is idempotent +
    safe to call manually from a migration / repair script too.

    Returns the new list for caller introspection.
    """
    workflow = await get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    graph_obj = WorkflowGraph.model_validate(workflow.graph)
    workflow.enabled_event_types = _extract_event_types(graph_obj)
    await session.commit()
    await session.refresh(workflow)
    return list(workflow.enabled_event_types)


# --- Step 17: version history + rollback + import / export ----------


async def list_workflow_versions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[WorkflowVersion], int]:
    """Paginated version history for one workflow. Returns ``(rows,
    total)`` so the drawer can render newest-first + show a
    `<count of total>` counter. Raises :class:`WorkflowNotFound` if
    the workflow doesn't belong to the org."""
    await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    rows = await _da.list_versions(
        session,
        org_id=org_id,
        workflow_id=workflow_id,
        limit=limit,
        offset=offset,
    )
    total = await _da.count_versions(
        session, org_id=org_id, workflow_id=workflow_id
    )
    return rows, total


async def get_workflow_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version: int,
) -> WorkflowVersion:
    """Resolve a specific historical version. Raises
    :class:`WorkflowNotFound` for both unknown workflow + unknown
    version (we don't want to leak which one is missing — same
    contract as the templates module)."""
    await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    row = await _da.get_version(
        session,
        org_id=org_id,
        workflow_id=workflow_id,
        version=version,
    )
    if row is None:
        raise WorkflowNotFound(
            f"workflow {workflow_id} has no version {version}"
        )
    return row


async def rollback_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    target_version: int,
    change_note: str | None = None,
) -> Workflow:
    """Copy the target version's graph back onto the live workflow.

    Bumps ``current_version`` and lands a NEW row in
    ``tbl_workflow_versions`` (preserving the audit chain — rolling
    back to v3 from v7 lands v8 with v3's graph). Active marketing
    workflows are locked out — same rule as
    :func:`update_workflow` (operator pauses, rolls back, reactivates).

    Re-validates the rolled-back graph against the current DB —
    template / sub-workflow references that were valid at the time
    of the version snapshot may have been archived since.
    """
    workflow = await get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    if _is_marketing_locked(workflow):
        raise WorkflowLocked(
            "cannot roll back an active marketing workflow; pause it first"
        )

    target = await _da.get_version(
        session,
        org_id=org_id,
        workflow_id=workflow_id,
        version=target_version,
    )
    if target is None:
        raise WorkflowNotFound(
            f"workflow {workflow_id} has no version {target_version}"
        )

    graph_dict = dict(target.graph or {})
    graph_obj = WorkflowGraph.model_validate(graph_dict)
    await validate_graph_with_db(
        session,
        org_id=org_id,
        graph=graph_obj,
        goal_node_id=workflow.goal_node_id,
    )

    workflow.graph = graph_obj.model_dump()
    workflow.enabled_event_types = _extract_event_types(graph_obj)
    workflow.current_version = workflow.current_version + 1
    workflow.updated_by_user_id = user_id

    note = change_note or f"Rolled back to v{target_version}"
    new_version = WorkflowVersion(
        org_id=org_id,
        workflow_id=workflow.id,
        version=workflow.current_version,
        graph=workflow.graph,
        change_note=note,
        created_by_user_id=user_id,
    )
    _da.add_version(session, new_version)

    await session.commit()
    await session.refresh(workflow)
    return workflow


async def export_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> dict:
    """Pure dict serializer for the JSON-export endpoint. Shape
    matches :class:`schemas.WorkflowExport`. Internal UUIDs
    (template_id references, etc.) are kept verbatim; the importer
    remaps unknown references to ``null``."""
    workflow = await get_workflow(
        session, org_id=org_id, workflow_id=workflow_id
    )
    return {
        "name": workflow.name,
        "description": workflow.description,
        "category": workflow.category,
        "graph": dict(workflow.graph or {}),
        "re_enrollment_rule": (
            workflow.re_enrollment_rule.value
            if hasattr(workflow.re_enrollment_rule, "value")
            else str(workflow.re_enrollment_rule)
        ),
        "is_marketing": bool(workflow.is_marketing),
        "goal_node_id": workflow.goal_node_id,
        "cost_per_run_cents": int(workflow.cost_per_run_cents or 0),
        "schema_version": 1,
    }


async def import_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: WorkflowCreate,
    target_folder_id: uuid.UUID | None = None,
    override_name: str | None = None,
) -> Workflow:
    """Persist an imported workflow as a draft.

    Caller (router) has already validated the JSON shape via
    :class:`schemas.WorkflowImportRequest`. This function:

      * applies the optional ``override_name`` (falls back to the
        payload's name);
      * auto-uniqifies the name if it clashes with an existing
        workflow in the org (``(2)``, ``(3)``, … suffix);
      * remaps unknown ``template_id`` references on send +
        record.create_* nodes to ``null`` + stamps
        ``__valid=false`` so the Step-15 editor surfaces them;
      * delegates persistence to :func:`create_workflow` so the
        graph validator + initial version row land as on a normal
        create.
    """
    # Auto-uniqify the name.
    desired = (override_name or payload.name).strip()
    existing_names = {
        name for name in await _da.list_workflow_names(session, org_id=org_id)
    }
    final_name = _next_unique_name(desired, existing_names)

    # Remap unknown template_ids → null. Pulls the existing template
    # ids in the org once so we can fast-check membership.
    from src.app.core.templates import data_access as templates_da

    graph_dict = dict(payload.graph.model_dump())
    nodes = list(graph_dict.get("nodes") or [])
    referenced_ids: set[uuid.UUID] = set()
    for node in nodes:
        cfg = (node.get("config") or {}) if isinstance(node, dict) else {}
        tid = cfg.get("template_id")
        if isinstance(tid, str):
            try:
                referenced_ids.add(uuid.UUID(tid))
            except ValueError:
                pass

    valid_ids: set[uuid.UUID] = set()
    for tid in referenced_ids:
        row = await templates_da.get_template(
            session, org_id=org_id, template_id=tid
        )
        if row is not None:
            valid_ids.add(tid)

    new_nodes: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            new_nodes.append(node)
            continue
        node_type = str(node.get("type") or "")
        cfg = dict(node.get("config") or {})
        if node_type.startswith("send.") or node_type.startswith("record.create_"):
            tid_raw = cfg.get("template_id")
            keep = False
            if isinstance(tid_raw, str):
                try:
                    keep = uuid.UUID(tid_raw) in valid_ids
                except ValueError:
                    keep = False
            if not keep:
                cfg.pop("template_id", None)
                cfg["__valid"] = False
        new_nodes.append({**node, "config": cfg})

    graph_dict["nodes"] = new_nodes

    create_payload = WorkflowCreate(
        name=final_name,
        description=payload.description,
        category=payload.category,
        folder_id=target_folder_id,
        is_marketing=payload.is_marketing,
        re_enrollment_rule=payload.re_enrollment_rule,
        graph=WorkflowGraph.model_validate(graph_dict),
        goal_node_id=payload.goal_node_id,
        cost_per_run_cents=payload.cost_per_run_cents,
    )
    return await create_workflow(
        session, org_id=org_id, user_id=user_id, payload=create_payload
    )


def _next_unique_name(base: str, existing: set[str]) -> str:
    """Bump ``base`` to ``base (2)``, ``base (3)``, … until unused."""
    if base not in existing:
        return base
    n = 2
    while True:
        candidate = f"{base} ({n})"
        if candidate not in existing:
            return candidate
        n += 1


__all__ = [
    "archive_workflow",
    "change_status",
    "create_folder",
    "create_workflow",
    "delete_folder",
    "export_workflow",
    "get_workflow",
    "get_workflow_version",
    "import_workflow",
    "list_folders",
    "list_workflow_versions",
    "list_workflows",
    "patch_folder",
    "rollback_workflow",
    "update_enabled_event_types_from_graph",
    "update_workflow",
]
