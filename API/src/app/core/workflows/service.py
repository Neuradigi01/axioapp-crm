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

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from croniter import CroniterBadCronError, CroniterBadDateError, croniter
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import data_access as _da
from src.app.core.workflows._croniter_timeout import (
    RecurrenceTimeout,
    run_with_timeout,
)
from src.app.core.workflows.exceptions import (
    DuplicateWorkflowName,
    FolderHasWorkflows,
    InvalidGraph,
    WorkflowLocked,
    WorkflowNotFound,
)
from src.app.core.workflows.graph import validate_graph_with_db
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    DeactivationReason,
    OnMissedPolicy,
    ScheduleKind,
    TriggerKind,
    Workflow,
    WorkflowFolder,
    WorkflowReEnrollmentRule,
    WorkflowRunStatus,
    WorkflowSchedule,
    WorkflowStatus,
    WorkflowVersion,
)
from src.app.core.workflows.schemas import (
    WorkflowCreate,
    WorkflowFolderCreate,
    WorkflowGraph,
    WorkflowUpdate,
)
from src.app.shared.audit import log_entity_change

logger = logging.getLogger(__name__)

# Status transitions the service allows. Any transition not in
# this set raises a :class:`ValueError` — the router maps to 409.
_ALLOWED_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.draft: frozenset({WorkflowStatus.active, WorkflowStatus.archived}),
    WorkflowStatus.active: frozenset({WorkflowStatus.paused, WorkflowStatus.archived}),
    WorkflowStatus.paused: frozenset({WorkflowStatus.active, WorkflowStatus.archived}),
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
    return bool(workflow.status == WorkflowStatus.active and workflow.is_marketing)


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
    existing = await _da.get_workflow_by_name(session, org_id=org_id, name=payload.name)
    if existing is not None:
        raise DuplicateWorkflowName(f"workflow named '{payload.name}' already exists")

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
    row = await _da.get_workflow(session, org_id=org_id, workflow_id=workflow_id)
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


async def list_workflows_with_schedule_summary(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: WorkflowStatus | None = None,
    category: str | None = None,
    folder_id: uuid.UUID | None = None,
    q: str | None = None,
    has_schedule: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Workflow, int, datetime | None]], int]:
    """List variant used by the list page (workflow-scheduling
    Step 5). Passthrough to the DAL — pagination, filters, and the
    schedule-summary aggregate all live in SQL to avoid N+1 across
    hundreds of workflows."""
    return await _da.list_workflows_with_schedule_summary(
        session,
        org_id=org_id,
        status=status,
        category=category,
        folder_id=folder_id,
        q=q,
        has_schedule=has_schedule,
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
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)

    changes = payload.model_dump(exclude_unset=True)

    # Marketing lock — active marketing workflows reject edits that
    # could disturb an in-flight enrolment (graph, name, category,
    # trigger, etc.). Pure metadata moves (folder_id) are safe because
    # they don't affect the running graph, so we allow those through
    # even on locked rows. Same rationale as archive/activate not
    # requiring a pause.
    _METADATA_ONLY_KEYS: frozenset[str] = frozenset({"folder_id"})
    is_metadata_only = bool(changes) and set(changes.keys()).issubset(_METADATA_ONLY_KEYS)
    if not is_metadata_only and _is_marketing_locked(workflow):
        raise WorkflowLocked("cannot edit an active marketing workflow; pause it first")

    # Cross-org / non-existent folder guard. Turns an otherwise
    # opaque 500 (FK violation from Postgres) into a friendly 404
    # the SPA can render. RLS keeps ``get_folder`` scoped to the
    # caller's tenant, so a cross-org uuid returns None.
    if "folder_id" in changes and changes["folder_id"] is not None:
        target_folder = await _da.get_folder(session, org_id=org_id, folder_id=changes["folder_id"])
        if target_folder is None:
            raise WorkflowNotFound(f"folder {changes['folder_id']} not found")

    # Snapshot the folder_id BEFORE we mutate so we can emit an audit
    # entry after commit. Only capture when folder_id is actually in
    # the payload — no point walking the audit path for pure graph
    # edits. The workflow update path historically had no audit trail;
    # adding it just for folder moves closes the compliance gap around
    # organisational reshuffles (who moved what, when).
    folder_before: uuid.UUID | None = workflow.folder_id if "folder_id" in changes else None
    audit_folder_change = "folder_id" in changes and workflow.folder_id != changes["folder_id"]

    # Name uniqueness re-check when renaming.
    new_name = changes.get("name")
    if new_name is not None and new_name.strip().lower() != workflow.name.lower():
        clash = await _da.get_workflow_by_name(session, org_id=org_id, name=new_name)
        if clash is not None and clash.id != workflow.id:
            raise DuplicateWorkflowName(f"workflow named '{new_name}' already exists")

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
    #
    # Fields where an explicit ``null`` payload MUST be honoured (the
    # user is clearing a nullable column — e.g. moving a workflow out
    # of every folder into "No folder", or removing a goal node).
    # Distinguished from the plain list below where NULL either isn't
    # allowed by the DB or wouldn't make sense semantically.
    for key in ("folder_id", "goal_node_id", "description"):
        if key in changes:
            setattr(workflow, key, changes[key])
    # Remaining scalar fields keep the legacy "ignore null" guard —
    # `name` / `category` / `is_marketing` / `cost_per_run_cents` are
    # NOT NULL columns; the guard treats a null payload as "no change"
    # rather than raising a DB IntegrityError.
    for key in ("name", "category", "is_marketing", "cost_per_run_cents"):
        if key in changes and changes[key] is not None:
            setattr(workflow, key, changes[key])

    if "re_enrollment_rule" in changes and changes["re_enrollment_rule"] is not None:
        workflow.re_enrollment_rule = WorkflowReEnrollmentRule(changes["re_enrollment_rule"])

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

    # After-commit audit for folder moves — kept post-commit so an
    # audit-sink failure can't roll the move back. Emits a minimal
    # {before, after} folder_id pair keyed to the workflow entity.
    if audit_folder_change:
        await log_entity_change(
            action="workflows.folder_changed",
            entity_type="workflow",
            entity_id=workflow.id,
            before={"folder_id": str(folder_before) if folder_before else None},
            after={"folder_id": str(workflow.folder_id) if workflow.folder_id else None},
        )
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
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    target = new_status if isinstance(new_status, WorkflowStatus) else WorkflowStatus(new_status)
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
            f"invalid status transition {workflow.status.value!r} → {new_status.value!r}"
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
    runs continue under the archived version (immutable history).

    Step 21 — system-default workflows (the day-one safety nets:
    Lead Auto-Triage, Deal Won Slack, Daily Digest) refuse archive.
    Operator can pause + edit them but not remove. Re-installing
    requires the seeder, which is operator-only via the backfill
    migration."""
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    if workflow.is_system_default:
        raise WorkflowLocked(
            "cannot archive a system-default workflow — pause it "
            "instead. System defaults are the CRM's day-one safety "
            "nets and stay in the org."
        )
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


async def list_folders(session: AsyncSession, *, org_id: uuid.UUID) -> list[WorkflowFolder]:
    return await _da.list_folders(session, org_id=org_id)


async def list_custom_event_types_for_picker(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[dict[str, str]]:
    """Return the org's live custom events shaped for the trigger
    picker: ``{event_type, label, description}``. Merged into the
    built-in catalog by the frontend so a workflow can trigger on any
    ``custom.<key>`` event fired via ``POST /custom-events/{id}/fire``.
    """
    from src.app.core.custom_events import service as custom_events_service

    entries = await custom_events_service.list_for_workflow_picker(session, org_id=org_id)
    return [
        {
            "event_type": entry["event_type"],
            "label": entry["label"],
            "description": entry["description"],
        }
        for entry in entries
    ]


async def patch_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    folder_id: uuid.UUID,
    name: str | None = None,
    parent_folder_id: uuid.UUID | None = None,
    display_order: int | None = None,
) -> WorkflowFolder:
    folder = await _da.get_folder(session, org_id=org_id, folder_id=folder_id)
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
    folder = await _da.get_folder(session, org_id=org_id, folder_id=folder_id)
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
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
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
    total = await _da.count_versions(session, org_id=org_id, workflow_id=workflow_id)
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
        raise WorkflowNotFound(f"workflow {workflow_id} has no version {version}")
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
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    if _is_marketing_locked(workflow):
        raise WorkflowLocked("cannot roll back an active marketing workflow; pause it first")

    target = await _da.get_version(
        session,
        org_id=org_id,
        workflow_id=workflow_id,
        version=target_version,
    )
    if target is None:
        raise WorkflowNotFound(f"workflow {workflow_id} has no version {target_version}")

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
    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
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
    existing_names = {name for name in await _da.list_workflow_names(session, org_id=org_id)}
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
        row = await templates_da.get_template(session, org_id=org_id, template_id=tid)
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
    return await create_workflow(session, org_id=org_id, user_id=user_id, payload=create_payload)


# --- Step 18: A/B pairing + unpair + stats ---------------------------


async def pair_for_ab(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    sibling_id: uuid.UUID,
    holdback_seconds: int,
    metric: str,
    min_runs_per_variant: int,
) -> tuple[Workflow, Workflow]:
    """Pair two drafts as an A/B test + flip both to active.

    Refuses (via :class:`InvalidGraph`) when:

      * the two workflows aren't both ``status='draft'``;
      * their trigger ``event_type``s differ — the engine can't
        50/50 a contact when the matchers fire on different events;
      * either workflow lacks a goal node — the winner-picker has
        no signal to score on;
      * either is already paired.

    On success: stamps ``ab_paired_workflow_id`` on both rows, sets
    ``ab_test_started_at = now()``, ``ab_test_holdback_until = now()
    + holdback_seconds``, persists the chosen metric +
    min-runs-per-variant, and transitions both to
    ``status='active'``.
    """
    from src.app.core.workflows.models import ABWinnerMetric

    if workflow_id == sibling_id:
        raise InvalidGraph("A/B pair refused: workflow can't pair with itself")

    primary = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    sibling = await get_workflow(session, org_id=org_id, workflow_id=sibling_id)

    if primary.status != WorkflowStatus.draft:
        raise InvalidGraph(
            f"A/B pair refused: primary workflow is '{primary.status.value}', expected 'draft'"
        )
    if sibling.status != WorkflowStatus.draft:
        raise InvalidGraph(
            f"A/B pair refused: sibling workflow is '{sibling.status.value}', expected 'draft'"
        )
    if primary.ab_paired_workflow_id is not None or sibling.ab_paired_workflow_id is not None:
        raise InvalidGraph("A/B pair refused: one of the workflows is already paired")

    primary_events = set(primary.enabled_event_types or [])
    sibling_events = set(sibling.enabled_event_types or [])
    if not primary_events or primary_events != sibling_events:
        raise InvalidGraph(
            "A/B pair refused: both workflows must share the same trigger event_type(s)"
        )
    if primary.goal_node_id is None or sibling.goal_node_id is None:
        raise InvalidGraph("A/B pair refused: both workflows must define a goal node")

    now = datetime.now(UTC)
    holdback_until = now + timedelta(seconds=holdback_seconds)
    chosen_metric = ABWinnerMetric(metric)

    for wf in (primary, sibling):
        wf.ab_paired_workflow_id = sibling.id if wf.id == primary.id else primary.id
        wf.ab_test_started_at = now
        wf.ab_test_holdback_until = holdback_until
        wf.ab_test_winner_metric = chosen_metric
        wf.ab_test_min_runs_per_variant = min_runs_per_variant
        wf.ab_test_winner_workflow_id = None
        wf.ab_test_decided_at = None
        wf.status = WorkflowStatus.active
        wf.updated_by_user_id = user_id

    await session.commit()
    await session.refresh(primary)
    await session.refresh(sibling)
    return primary, sibling


async def unpair_ab(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
) -> Workflow:
    """Operator-initiated early cancel of an A/B test.

    Both workflows stay in their current status (no auto-archive of
    either side); new enrolments stop splitting. The paired
    pointers + holdback metadata are cleared. In-flight runs
    continue to completion.
    """
    primary = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    sibling_id = primary.ab_paired_workflow_id
    if sibling_id is None:
        raise InvalidGraph("A/B unpair refused: workflow isn't part of an A/B test")
    sibling = await _da.get_workflow(session, org_id=org_id, workflow_id=sibling_id)

    for wf in (primary, sibling):
        if wf is None:
            continue
        wf.ab_paired_workflow_id = None
        wf.ab_test_started_at = None
        wf.ab_test_holdback_until = None
        wf.ab_test_winner_workflow_id = None
        wf.ab_test_decided_at = None
        wf.updated_by_user_id = user_id

    await session.commit()
    await session.refresh(primary)
    return primary


async def get_ab_stats(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> dict:
    """Compute live A/B stats for the canvas banner + comparison page.

    "A" / "B" labels follow the same lower-id-first ordering the
    picker uses so the banner stays stable regardless of which
    side the operator inspected.
    """
    from src.app.core.workflows import ab_testing

    primary = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    sibling_id = primary.ab_paired_workflow_id
    if sibling_id is None:
        raise InvalidGraph("A/B stats refused: workflow isn't part of an A/B test")
    sibling = await _da.get_workflow(session, org_id=org_id, workflow_id=sibling_id)
    if sibling is None:
        raise InvalidGraph("A/B stats: sibling workflow is missing — was it deleted?")

    a_workflow, b_workflow = (
        (primary, sibling) if str(primary.id) < str(sibling.id) else (sibling, primary)
    )
    min_runs = max(
        primary.ab_test_min_runs_per_variant or 50,
        sibling.ab_test_min_runs_per_variant or 50,
    )
    result = await ab_testing.pick_winner(
        session,
        a_workflow_id=a_workflow.id,
        b_workflow_id=b_workflow.id,
        min_runs_per_variant=min_runs,
    )
    return {
        "workflow_id": primary.id,
        "sibling_workflow_id": sibling.id,
        "a_workflow_id": a_workflow.id,
        "b_workflow_id": b_workflow.id,
        "a_total_runs": result.a_total,
        "a_goal_runs": result.a_goal,
        "a_rate": result.a_rate,
        "b_total_runs": result.b_total,
        "b_goal_runs": result.b_goal,
        "b_rate": result.b_rate,
        "p_value": result.p_value,
        "winner": result.winner,
        "holdback_until": primary.ab_test_holdback_until,
        "decided_at": primary.ab_test_decided_at,
        "min_runs_per_variant": min_runs,
    }


# --- Step 19: analytics + diagnostics ----------------------------------


async def get_workflow_analytics(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> dict:
    """Headline analytics for the Step-19 dashboard. Resolves the
    workflow (raises :class:`WorkflowNotFound` on miss / cross-tenant)
    + delegates to :mod:`core.workflows.analytics`."""
    from src.app.core.workflows import analytics as _analytics

    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    return await _analytics.compute_workflow_metrics(
        session,
        org_id=org_id,
        workflow=workflow,
        since=since,
        until=until,
    )


async def get_workflow_daily_rate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    days: int,
) -> list[dict]:
    """Daily sparkline series."""
    from src.app.core.workflows import analytics as _analytics

    workflow = await get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    return await _analytics.compute_daily_rate(
        session,
        org_id=org_id,
        workflow=workflow,
        days=days,
    )


async def get_run_detail(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> dict:
    """Compose the run-detail page payload: the run row, its parent
    workflow's id + name, and the ordered step_runs.

    Raises :class:`WorkflowNotFound` on miss (mapped to 404)."""
    from src.app.core.workflows.schemas import (
        WorkflowRunRead,
        WorkflowStepRunRead,
    )

    pair = await _da.get_run_with_workflow(session, org_id=org_id, run_id=run_id)
    if pair is None:
        raise WorkflowNotFound(f"run {run_id} not found")
    run, workflow = pair
    step_runs = await _da.list_step_runs(session, org_id=org_id, run_id=run_id)
    nodes_by_id = workflow.graph_nodes_by_id
    enriched_steps = []
    for step in step_runs:
        node = nodes_by_id.get(step.node_id) or {}
        config = node.get("config") or {}
        label = config.get("label") or config.get("name") or config.get("title") or step.node_id
        # Validate via the Pydantic schema so enum values coerce to
        # their string forms + the FastAPI encoder sees a plain dict
        # (not the SQLAlchemy ORM object).
        step_dict = WorkflowStepRunRead.model_validate(step).model_dump(mode="json")
        step_dict["node_label"] = label
        step_dict["node_type"] = node.get("type") or "unknown"
        enriched_steps.append(step_dict)
    return {
        "run": WorkflowRunRead.model_validate(run).model_dump(mode="json"),
        "workflow_id": str(workflow.id),
        "workflow_name": workflow.name,
        "steps": enriched_steps,
    }


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


# ---------------------------------------------------------------------------
# Workflow scheduling — ``tasks/workflow-scheduling`` Step 2
# ---------------------------------------------------------------------------
#
# The scheduling surface splits into three concerns, all owned by this file:
#
#   1. **CRUD** — create / update / pause / resume / delete schedule rows.
#      Endpoints in Step 3 call these; each writes an audit row.
#   2. **Recurrence math** — ``compute_next_run_at`` converts a schedule's
#      ``schedule_kind`` + ``config_json`` + ``timezone`` into the next UTC
#      firing datetime. Pure function; safe to call from anywhere.
#   3. **Sweep dispatch** — ``sweep_due_schedules`` walks the DAL's due-
#      query in bounded batches, and ``_dispatch_due_schedule`` fires one
#      schedule inside a per-row savepoint (RLS context set, concurrency
#      + rate checks, event publish, ``engine.start_run`` call, advance
#      ``next_run_at``, deactivation on terminal conditions).
#
# The sweep is called from ``tasks.sweep_waits`` — same 60s beat, no new
# beat entry (README locked decision).

# --- caps (README locked decisions) --------------------------------------

MAX_ACTIVE_SCHEDULES_PER_ORG = 500
MAX_FIRES_PER_HOUR_PER_ORG = 1000
MIN_INTER_FIRE_MINUTES = 5
MAX_SCHEDULE_HORIZON_YEARS = 5
CONSECUTIVE_EMPTY_DEACTIVATION_THRESHOLD = 20
SWEEP_BATCH_SIZE = 100


class ScheduleValidationError(Exception):
    """Service-layer input validation refused a schedule create/update.

    Router maps to 422 with ``reason`` as the detail. Distinct from
    :class:`InvalidGraph` so the router can format schedule vs graph
    errors differently."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ScheduleNotFound(Exception):
    """Schedule row missing (or cross-tenant). Router maps to 404 —
    never 403 (no info leak)."""


class ScheduleCapExceeded(Exception):
    """Per-org active-schedule cap reached. Router maps to 422 with a
    friendly "reached the N-schedule limit" message."""

    def __init__(self, cap: int) -> None:
        super().__init__(f"organization has reached the {cap}-schedule limit")
        self.cap = cap


# --- validation ----------------------------------------------------------


def _validate_timezone(tz_name: str) -> None:
    """Whitelist the tz string against ``zoneinfo.available_timezones()``
    so a typo (or a supply-chain-poisoned import) can't plant an
    unresolvable tz. Also protects the sweep — a bad tz raise on load
    would deactivate the schedule (see ``_dispatch_due_schedule``)."""
    if tz_name not in available_timezones():
        raise ScheduleValidationError(
            f"timezone must be a valid IANA identifier (got: {tz_name!r})"
        )
    # Second-line guard — catch imports whose whitelist is stale
    # relative to zoneinfo's actual data.
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleValidationError(f"timezone {tz_name!r} not resolvable") from exc


def _validate_config_and_bounds(
    *,
    schedule_kind: ScheduleKind,
    config: dict[str, Any],
    starts_at: datetime,
    end_at: datetime | None,
    max_runs: int | None,
    tz_name: str,
    now: datetime,
) -> None:
    """Reject any schedule that violates a locked decision. Called
    from create + update. Every raise carries a message the router
    surfaces verbatim as the 422 ``detail``."""
    _validate_timezone(tz_name)

    # Accept `starts_at` up to 5 minutes in the past so the natural
    # form-fill / network latency between "operator clicks now-ish"
    # and the server receiving the POST doesn't 422 (README Cases
    # §7). Anything older than 5 min is a genuine mistake (or a
    # form that sat open all day).
    if starts_at < now - timedelta(minutes=5):
        raise ScheduleValidationError("start time is in the past")
    if end_at is not None and end_at < starts_at:
        raise ScheduleValidationError("end time must be after start time")
    if max_runs is not None and max_runs < 1:
        raise ScheduleValidationError("max_runs must be >= 1 when set")

    kind_validators = {
        ScheduleKind.once: _validate_once_config,
        ScheduleKind.daily: _validate_daily_config,
        ScheduleKind.weekly: _validate_weekly_config,
        ScheduleKind.monthly: _validate_monthly_config,
        ScheduleKind.interval: _validate_interval_config,
        ScheduleKind.cron: _validate_cron_config,
    }
    kind_validators[schedule_kind](config, tz_name=tz_name, now=now)


def _parse_hhmm(value: object, *, field: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ScheduleValidationError(f"{field} must be a string like '09:00'")
    try:
        hh_str, mm_str = value.split(":", 1)
        hh, mm = int(hh_str), int(mm_str)
    except (ValueError, AttributeError) as exc:
        raise ScheduleValidationError(
            f"{field} must be 'HH:MM' 24-hour format (got {value!r})"
        ) from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ScheduleValidationError(f"{field} out of range (got {value!r})")
    return hh, mm


def _validate_once_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    at_iso = config.get("at")
    if not isinstance(at_iso, str):
        raise ScheduleValidationError("once schedules require config.at (ISO datetime)")
    try:
        at_dt = datetime.fromisoformat(at_iso)
    except ValueError as exc:
        raise ScheduleValidationError(
            f"config.at must be an ISO datetime (got {at_iso!r})"
        ) from exc
    if at_dt.tzinfo is None:
        # Naive → assume schedule's tz.
        at_dt = at_dt.replace(tzinfo=ZoneInfo(tz_name))
    if at_dt < now:
        raise ScheduleValidationError("once schedule's fire time is in the past")


def _validate_daily_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    _parse_hhmm(config.get("time"), field="config.time")


_WEEKDAY_NAMES = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _validate_weekly_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    days = config.get("days")
    if not isinstance(days, list) or not days:
        raise ScheduleValidationError(
            "weekly schedules require config.days (non-empty list, e.g. ['mon','wed'])"
        )
    for d in days:
        if not isinstance(d, str) or d.lower() not in _WEEKDAY_NAMES:
            raise ScheduleValidationError(
                f"weekly config.days must contain 3-letter day codes "
                f"(mon/tue/wed/thu/fri/sat/sun); got {d!r}"
            )
    _parse_hhmm(config.get("time"), field="config.time")


def _validate_monthly_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    day = config.get("day_of_month")
    if not isinstance(day, int) or not (1 <= day <= 31):
        raise ScheduleValidationError(
            "monthly config.day_of_month must be an int in 1..31 "
            "(31 clamps to the last day of shorter months)"
        )
    _parse_hhmm(config.get("time"), field="config.time")


_INTERVAL_UNITS = {"minutes", "hours", "days"}


def _validate_interval_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    unit = config.get("unit")
    every = config.get("every")
    if unit not in _INTERVAL_UNITS:
        raise ScheduleValidationError(
            f"interval config.unit must be one of {sorted(_INTERVAL_UNITS)}"
        )
    if not isinstance(every, int) or every < 1:
        raise ScheduleValidationError("interval config.every must be a positive integer")
    # Enforce the min-inter-fire floor (README locked decision).
    minutes = every * {"minutes": 1, "hours": 60, "days": 60 * 24}[unit]
    if minutes < MIN_INTER_FIRE_MINUTES:
        raise ScheduleValidationError(f"minimum interval is {MIN_INTER_FIRE_MINUTES} minutes")


def _validate_cron_config(config: dict[str, Any], *, tz_name: str, now: datetime) -> None:
    expr = config.get("expression")
    if not isinstance(expr, str) or not expr.strip():
        raise ScheduleValidationError(
            "cron schedules require config.expression (5-field cron string)"
        )
    # 5-field only — reject 6+ (with seconds or year).
    if len(expr.split()) != 5:
        raise ScheduleValidationError(
            "5-field cron only (minute hour day month weekday); "
            "seconds field and 6-field cron with year not supported"
        )
    tz = ZoneInfo(tz_name)
    now_local = now.astimezone(tz)
    try:
        it = croniter(expr, now_local)
        first = it.get_next(datetime)
        second = it.get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError) as exc:
        raise ScheduleValidationError(f"invalid cron expression: {exc}") from exc

    inter_fire = (second - first).total_seconds() / 60.0
    if inter_fire < MIN_INTER_FIRE_MINUTES:
        raise ScheduleValidationError(
            f"minimum inter-fire interval is {MIN_INTER_FIRE_MINUTES} minutes "
            f"(computed {inter_fire:.1f}m for this expression)"
        )

    horizon = now + timedelta(days=365 * MAX_SCHEDULE_HORIZON_YEARS)
    if first.astimezone(UTC) > horizon:
        raise ScheduleValidationError(
            f"schedule would not fire for over {MAX_SCHEDULE_HORIZON_YEARS} years"
        )


# --- recurrence math -----------------------------------------------------


def compute_next_run_at(
    schedule: WorkflowSchedule,
    *,
    now: datetime,
) -> datetime:
    """Compute the next UTC firing datetime for ``schedule``, given
    ``now`` (UTC). Wrapped in a 500ms hard timeout via
    :func:`_croniter_timeout.run_with_timeout` so a pathological cron
    can't stall the sweep.

    Raises:
        * :class:`RecurrenceTimeout` — compute exceeded 500ms.
        * :class:`ScheduleValidationError` — config is invalid
          (sweep catches, deactivates row with
          ``deactivation_reason='recurrence_invalid'``).

    For ``once`` schedules, returns the configured fire time if it's
    still in the future, else raises :class:`ScheduleValidationError`
    (once-schedules are meant to fire exactly once and terminate).
    """
    return run_with_timeout(_compute_next_run_at_inner, schedule, now, timeout_ms=500)


def _compute_next_run_at_inner(
    schedule: WorkflowSchedule,
    now: datetime,
) -> datetime:
    tz = ZoneInfo(schedule.timezone)
    config = schedule.config_json or {}
    base_utc = max(now, schedule.starts_at.astimezone(UTC))
    base_local = base_utc.astimezone(tz)

    kind = schedule.schedule_kind

    if kind == ScheduleKind.once:
        at_iso = config.get("at")
        if not isinstance(at_iso, str):
            raise ScheduleValidationError("once schedule missing config.at")
        at_dt = datetime.fromisoformat(at_iso)
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=tz)
        return at_dt.astimezone(UTC)

    if kind == ScheduleKind.daily:
        hh, mm = _parse_hhmm(config.get("time"), field="config.time")
        candidate = base_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= base_local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(UTC)

    if kind == ScheduleKind.weekly:
        days = [d.lower() for d in config.get("days") or []]
        wanted = {
            name: i for i, name in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        }
        wanted_idx = sorted({wanted[d] for d in days if d in wanted})
        if not wanted_idx:
            raise ScheduleValidationError("weekly schedule has no valid days")
        hh, mm = _parse_hhmm(config.get("time"), field="config.time")
        # Walk forward day-by-day up to 14 days looking for the next
        # matching (weekday, HH:MM) that is strictly after base_local.
        for delta_days in range(0, 15):
            cand = (base_local + timedelta(days=delta_days)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            if cand.weekday() in wanted_idx and cand > base_local:
                return cand.astimezone(UTC)
        # Fallback — should never hit given 14-day window covers a
        # full weekly cycle twice.
        raise ScheduleValidationError("weekly schedule could not resolve next fire")

    if kind == ScheduleKind.monthly:
        day = int(config.get("day_of_month") or 1)
        hh, mm = _parse_hhmm(config.get("time"), field="config.time")
        # Try current month first; if the clamped date is <= now,
        # jump to next month.
        year = base_local.year
        month = base_local.month
        for _ in range(2):
            clamped_day = _clamp_day_of_month(year, month, day)
            cand = base_local.replace(
                year=year,
                month=month,
                day=clamped_day,
                hour=hh,
                minute=mm,
                second=0,
                microsecond=0,
            )
            if cand > base_local:
                return cand.astimezone(UTC)
            month += 1
            if month > 12:
                month = 1
                year += 1
        raise ScheduleValidationError("monthly schedule could not resolve next fire")

    if kind == ScheduleKind.interval:
        unit = config.get("unit")
        every = int(config.get("every") or 0)
        seconds = every * {"minutes": 60, "hours": 3600, "days": 86400}.get(unit, 0)
        if seconds < MIN_INTER_FIRE_MINUTES * 60:
            raise ScheduleValidationError(f"interval too short (min {MIN_INTER_FIRE_MINUTES}m)")
        # If last_run_at is set, compute from there; otherwise from
        # base_utc. Forward-project past ``now`` so a long outage
        # doesn't leave us N intervals behind.
        anchor = schedule.last_run_at or base_utc
        anchor_utc = anchor.astimezone(UTC) if anchor.tzinfo else anchor.replace(tzinfo=UTC)
        candidate = anchor_utc + timedelta(seconds=seconds)
        if candidate <= now:
            # Forward-jump to first future slot.
            missed = (now - candidate).total_seconds() // seconds + 1
            candidate = candidate + timedelta(seconds=seconds * missed)
        return candidate

    if kind == ScheduleKind.cron:
        expr = config.get("expression")
        if not isinstance(expr, str):
            raise ScheduleValidationError("cron schedule missing config.expression")
        try:
            # croniter takes a tz-aware start_time and returns tz-aware
            # datetimes if given tz-aware input. We iterate until the
            # next fire is strictly > now (defensive; get_next already
            # does this but base_local may equal a fire boundary).
            it = croniter(expr, base_local)
            while True:
                nxt = it.get_next(datetime)
                if nxt.astimezone(UTC) > now:
                    return nxt.astimezone(UTC)
        except (CroniterBadCronError, CroniterBadDateError, ValueError) as exc:
            raise ScheduleValidationError(f"cron expression invalid on re-parse: {exc}") from exc

    raise ScheduleValidationError(f"unknown schedule_kind: {kind}")


def _clamp_day_of_month(year: int, month: int, day: int) -> int:
    """Clamp a day-of-month to the last valid day of the given month
    (day=31 → 28/29/30/31 depending on month + leap year)."""
    import calendar

    last = calendar.monthrange(year, month)[1]
    return min(day, last)


# --- CRUD services -------------------------------------------------------


async def _resolve_default_timezone(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> str:
    """Look up the org's ``timezone`` for use as the schedule default.
    Falls back to ``'UTC'`` when the org row is absent (shouldn't
    happen — RLS + FK ensure the row exists — but the fallback keeps
    the sweep from raising on data drift)."""
    from sqlalchemy import select as _select

    from src.app.core.tenants.models import Organization

    result = await session.execute(_select(Organization.timezone).where(Organization.id == org_id))
    tz = result.scalar_one_or_none()
    return tz or "UTC"


async def create_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    workflow_id: uuid.UUID,
    name: str,
    schedule_kind: ScheduleKind,
    config_json: dict[str, Any],
    starts_at: datetime,
    end_at: datetime | None,
    max_runs: int | None,
    timezone_name: str | None,
    contact_id: uuid.UUID | None,
    on_missed: OnMissedPolicy,
    concurrency_policy: ConcurrencyPolicy,
    now: datetime | None = None,
) -> WorkflowSchedule:
    """Create a schedule attached to a workflow. Cross-org guard:
    workflow must belong to ``org_id`` — else :class:`WorkflowNotFound`
    (router maps to 404 with no info leak).

    Enforces the per-org active-schedule cap in the same transaction
    as the insert so two racing requests can't slip past 500.

    Writes ``workflow.schedule_created`` audit event on success."""
    now = now or datetime.now(UTC)

    # Cross-org guard — reuse the existing DAL loader.
    workflow = await _da.get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    if workflow is None:
        raise WorkflowNotFound(f"workflow {workflow_id} not found in org {org_id}")

    tz_name = timezone_name or await _resolve_default_timezone(session, org_id=org_id)

    _validate_config_and_bounds(
        schedule_kind=schedule_kind,
        config=config_json,
        starts_at=starts_at,
        end_at=end_at,
        max_runs=max_runs,
        tz_name=tz_name,
        now=now,
    )

    # Cap check inside the same txn as insert prevents race past 500.
    active_count = await _da.count_active_schedules_for_org(session, org_id=org_id)
    if active_count >= MAX_ACTIVE_SCHEDULES_PER_ORG:
        raise ScheduleCapExceeded(MAX_ACTIVE_SCHEDULES_PER_ORG)

    schedule = WorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        contact_id=contact_id,
        name=name,
        schedule_kind=schedule_kind,
        config_json=config_json,
        timezone=tz_name,
        starts_at=starts_at,
        end_at=end_at,
        max_runs=max_runs,
        active=True,
        on_missed=on_missed,
        concurrency_policy=concurrency_policy,
        created_by_user_id=user_id,
    )
    # Compute the first fire before insert so the sweep picks it up
    # on the next tick.
    schedule.next_run_at = compute_next_run_at(schedule, now=now)

    await _da.insert_schedule(session, schedule=schedule)
    await session.commit()
    await session.refresh(schedule)

    await log_entity_change(
        action="workflows.schedule_created",
        entity_type="workflow_schedule",
        entity_id=schedule.id,
        after={
            "workflow_id": str(workflow_id),
            "name": name,
            "schedule_kind": schedule_kind.value,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        },
    )
    return schedule


async def update_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    schedule_id: uuid.UUID,
    fields: dict[str, Any],
    if_match_updated_at: datetime,
    now: datetime | None = None,
) -> WorkflowSchedule:
    """Partial update. ``if_match_updated_at`` is the ETag the caller
    pulled off the last GET; a mismatch → :class:`WorkflowLocked`
    (router maps to 409). Recomputes ``next_run_at`` when any
    recurrence-affecting field changes; resets
    ``consecutive_empty_fires`` (operator-supervision signal)."""
    now = now or datetime.now(UTC)

    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None:
        raise ScheduleNotFound(f"schedule {schedule_id} not found in org {org_id}")

    # Optimistic-lock check — reject stale writers.
    if _isoformat_no_micros(schedule.updated_at) != _isoformat_no_micros(if_match_updated_at):
        raise WorkflowLocked("schedule was modified concurrently; re-fetch and retry")

    # Build the new proposed state so re-validation can see the
    # merged payload.
    merged_kind: ScheduleKind = fields.get("schedule_kind", schedule.schedule_kind)
    merged_config: dict[str, Any] = fields.get("config_json", schedule.config_json or {})
    merged_starts: datetime = fields.get("starts_at", schedule.starts_at)
    merged_end: datetime | None = fields.get("end_at", schedule.end_at)
    merged_max: int | None = fields.get("max_runs", schedule.max_runs)
    merged_tz: str = fields.get("timezone", schedule.timezone)

    _validate_config_and_bounds(
        schedule_kind=merged_kind,
        config=merged_config,
        starts_at=merged_starts,
        end_at=merged_end,
        max_runs=merged_max,
        tz_name=merged_tz,
        now=now,
    )

    # Reset the empty-fires counter — the operator touched the config,
    # so any prior "always empty" signal is stale.
    fields.setdefault("consecutive_empty_fires", 0)

    # Recompute next_run_at if any recurrence-affecting field changed.
    recurrence_dirty = bool(
        {"schedule_kind", "config_json", "starts_at", "timezone"} & fields.keys()
    )
    if recurrence_dirty:
        # Build a hydrated in-memory schedule for the compute call
        # (the row on session may not yet reflect the new fields).
        preview = WorkflowSchedule(
            org_id=schedule.org_id,
            workflow_id=schedule.workflow_id,
            name=schedule.name,
            schedule_kind=merged_kind,
            config_json=merged_config,
            timezone=merged_tz,
            starts_at=merged_starts,
        )
        try:
            fields["next_run_at"] = compute_next_run_at(preview, now=now)
        except (ScheduleValidationError, RecurrenceTimeout) as exc:
            raise ScheduleValidationError(str(exc)) from exc

    rowcount = await _da.update_schedule_fields(
        session, org_id=org_id, schedule_id=schedule_id, fields=fields
    )
    await session.commit()
    if rowcount == 0:
        # Extremely unlikely — row was deleted between load and update.
        raise ScheduleNotFound(f"schedule {schedule_id} vanished mid-update")

    refreshed = await _da.get_schedule_by_id_and_org(
        session, org_id=org_id, schedule_id=schedule_id
    )
    await log_entity_change(
        action="workflows.schedule_updated",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
        before={"updated_at": _isoformat_no_micros(if_match_updated_at)},
        after={k: _to_json_safe(v) for k, v in fields.items()},
    )
    return refreshed  # type: ignore[return-value]


async def pause_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    schedule_id: uuid.UUID,
) -> WorkflowSchedule:
    """Pause = set ``active=false`` with ``deactivation_reason='manual'``.
    ``next_run_at`` is frozen; resume recomputes forward from now."""
    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None:
        raise ScheduleNotFound(f"schedule {schedule_id} not found in org {org_id}")
    if not schedule.active:
        return schedule  # already paused / ended — idempotent
    await _da.update_schedule_fields(
        session,
        org_id=org_id,
        schedule_id=schedule_id,
        fields={
            "active": False,
            "deactivation_reason": DeactivationReason.manual,
        },
    )
    await session.commit()
    refreshed = await _da.get_schedule_by_id_and_org(
        session, org_id=org_id, schedule_id=schedule_id
    )
    await log_entity_change(
        action="workflows.schedule_paused",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
    )
    return refreshed  # type: ignore[return-value]


async def resume_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    schedule_id: uuid.UUID,
    now: datetime | None = None,
) -> WorkflowSchedule:
    """Resume = clear ``active=false`` + recompute ``next_run_at``
    from now. Refuses if the row was deactivated by natural
    exhaustion (max_runs / end_at / ended) — those need a fresh
    schedule, not a resume."""
    now = now or datetime.now(UTC)
    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None:
        raise ScheduleNotFound(f"schedule {schedule_id} not found in org {org_id}")
    if schedule.active:
        return schedule  # already active — idempotent

    terminal_reasons = {
        DeactivationReason.max_runs,
        DeactivationReason.end_at,
        DeactivationReason.ended,
    }
    if schedule.deactivation_reason in terminal_reasons:
        raise ScheduleValidationError(
            "schedule ended naturally; create a new schedule instead of resuming"
        )

    # Recompute next fire from now.
    try:
        next_at = compute_next_run_at(schedule, now=now)
    except (ScheduleValidationError, RecurrenceTimeout) as exc:
        raise ScheduleValidationError(f"cannot resume: {exc}") from exc

    await _da.update_schedule_fields(
        session,
        org_id=org_id,
        schedule_id=schedule_id,
        fields={
            "active": True,
            "deactivation_reason": None,
            "next_run_at": next_at,
            "consecutive_empty_fires": 0,
        },
    )
    await session.commit()
    refreshed = await _da.get_schedule_by_id_and_org(
        session, org_id=org_id, schedule_id=schedule_id
    )
    await log_entity_change(
        action="workflows.schedule_resumed",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
        after={"next_run_at": next_at.isoformat()},
    )
    return refreshed  # type: ignore[return-value]


async def cascade_schedules_on_contact_delete(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> int:
    """Called from ``contacts.service.delete_contact`` BEFORE the
    contact row is dropped. Deactivates every schedule directly
    targeting the deleted contact — the FK's ``ON DELETE SET NULL``
    would silently orphan them otherwise (schedule fires with
    ``contact_id = None`` → send actions skip with
    ``recipient_not_found``, wasting the fire budget).

    Writes one ``workflows.schedule_deactivated`` audit event per
    row + notifies the workflow owner via the notifications service.
    Returns the row count deactivated (caller may include it in the
    contact-delete audit summary).

    NOOP when the contact has no schedules — no audit, no
    notifications."""
    schedules = await _da.list_schedules_for_contact(session, org_id=org_id, contact_id=contact_id)
    if not schedules:
        return 0
    for schedule in schedules:
        if not schedule.active:
            continue
        await _da.update_schedule_fields(
            session,
            org_id=org_id,
            schedule_id=schedule.id,
            fields={
                "active": False,
                "deactivation_reason": DeactivationReason.contact_deleted,
                "next_run_at": None,
            },
        )
    # Commit here so the schedule rows are durably deactivated even
    # if the caller's later delete-contact commit fails — orphan-
    # schedule-with-live-contact is a better failure mode than
    # deleted-contact-with-still-firing-schedule.
    await session.commit()

    for schedule in schedules:
        await log_entity_change(
            action="workflows.schedule_deactivated",
            entity_type="workflow_schedule",
            entity_id=schedule.id,
            after={
                "reason": DeactivationReason.contact_deleted.value,
                "workflow_id": str(schedule.workflow_id),
                "contact_id": str(contact_id),
            },
        )
        await _notify_schedule_owner_deactivated(
            schedule,
            reason=DeactivationReason.contact_deleted,
        )
    return len(schedules)


async def deactivate_schedule_for_empty_fires(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> None:
    """Called from the schedule dispatch loop when
    ``consecutive_empty_fires`` reaches the deactivation threshold
    (README locked decision: 20). Writes the audit + emails the
    workflow owner so a silently-broken schedule doesn't stay
    silently broken."""
    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None or not schedule.active:
        return
    await _da.update_schedule_fields(
        session,
        org_id=org_id,
        schedule_id=schedule_id,
        fields={
            "active": False,
            "deactivation_reason": DeactivationReason.consecutive_empty,
            "next_run_at": None,
        },
    )
    await session.commit()
    await log_entity_change(
        action="workflows.schedule_deactivated",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
        after={
            "reason": DeactivationReason.consecutive_empty.value,
            "consecutive_empty_fires": schedule.consecutive_empty_fires,
        },
    )
    await _notify_schedule_owner_deactivated(
        schedule,
        reason=DeactivationReason.consecutive_empty,
    )


async def increment_consecutive_empty_fires_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> int:
    """Called from the send-action handler when a scheduled run
    resolves to ``recipient_not_found`` — the closest signal to
    "this schedule fired but reached no one". Returns the post-
    increment value so the caller can decide whether to trigger
    deactivation on this same fire."""
    return await _da.bump_consecutive_empty_fires(session, org_id=org_id, schedule_id=schedule_id)


async def reset_consecutive_empty_fires_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> None:
    """Called from the send-action handler on a successful send —
    the schedule is doing something useful, reset the counter."""
    await _da.reset_consecutive_empty_fires(session, org_id=org_id, schedule_id=schedule_id)


async def reap_orphaned_pending_runs(
    *,
    older_than_minutes: int = 60,
    limit: int = 100,
) -> dict[str, int]:
    """Beat helper — mark ``pending`` runs whose ``started_at`` is
    older than ``older_than_minutes`` as ``errored`` with
    ``error='orphaned_pending'``. These are runs the engine
    committed but the celery worker died before dispatching, so no
    subsequent hop is coming — leaving them ``pending`` forever
    pollutes the analytics + prevents contact re-enrolment.

    Called from ``sweep_waits`` after the schedule dispatch phase.
    Rate-limited to ``limit`` reaps per tick so a large backlog
    unwinds gradually.
    """
    from sqlalchemy import update as _sql_update

    from src.app.shared.db import async_session

    reaped = 0
    async with async_session() as sess:
        threshold = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        orphans = await _da.select_orphaned_pending_runs(sess, older_than=threshold, limit=limit)
        if not orphans:
            return {"reaped": 0}
        ids = [r.id for r in orphans]
        # Batch UPDATE — one round-trip regardless of orphan count.
        from src.app.core.workflows.models import WorkflowRun

        await sess.execute(
            _sql_update(WorkflowRun)
            .where(WorkflowRun.id.in_(ids))
            .values(
                status=WorkflowRunStatus.errored,
                error="orphaned_pending",
                completed_at=datetime.now(UTC),
            )
        )
        await sess.commit()
        reaped = len(ids)
        for r in orphans:
            logger.warning(
                "workflows.reap_orphan run=%s org=%s workflow=%s",
                r.id,
                r.org_id,
                r.workflow_id,
            )
    return {"reaped": reaped}


async def sweep_orphan_schedules() -> dict[str, int]:
    """Weekly beat helper — schedule rows whose parent workflow row
    is missing. FK CASCADE should prevent this from ever existing;
    this is a safety net for historical bugs (dev fixtures restored
    mid-migration, raw SQL delete bypassing FK). Logs findings +
    writes one audit event per orphan; does NOT auto-delete — the
    operator makes that call.
    """
    from src.app.shared.db import async_session

    async with async_session() as sess:
        orphans = await _da.list_orphan_schedules(sess, limit=500)
    if orphans:
        logger.warning("workflows.sweep_orphan_schedules found %d orphan(s)", len(orphans))
        for s in orphans:
            await log_entity_change(
                action="workflows.schedule_orphaned",
                entity_type="workflow_schedule",
                entity_id=s.id,
                after={
                    "workflow_id": str(s.workflow_id),
                    "org_id": str(s.org_id),
                    "note": (
                        "schedule row exists but parent workflow is missing; "
                        "FK CASCADE should have dropped it — historical drift"
                    ),
                },
            )
    return {"found": len(orphans)}


async def _notify_schedule_owner_deactivated(
    schedule: WorkflowSchedule,
    *,
    reason: DeactivationReason,
) -> None:
    """Best-effort — email + in-app notification to the schedule's
    creator (or the workflow's owner if creator is null). NEVER
    raises — a notifications outage must not prevent the schedule
    deactivation from committing.

    Natural exhaustion (``ended`` / ``max_runs`` / ``end_at``) is
    expected — no notification. Every other reason emails so the
    operator sees the silent-off state."""
    natural_exhaustion = {
        DeactivationReason.ended,
        DeactivationReason.max_runs,
        DeactivationReason.end_at,
    }
    if reason in natural_exhaustion:
        return
    if schedule.created_by_user_id is None:
        return
    try:
        from src.app.core.notifications import service as notifications_service

        await notifications_service.notify(
            org_id=schedule.org_id,
            user_id=schedule.created_by_user_id,
            type="workflow.schedule_deactivated",
            title=f"Schedule paused: {schedule.name}",
            body=(
                f"Your workflow schedule '{schedule.name}' has been "
                f"deactivated ({reason.value}). Reopen the workflow to "
                "review + reactivate."
            ),
            payload={
                "workflow_id": str(schedule.workflow_id),
                "schedule_id": str(schedule.id),
                "schedule_name": schedule.name,
                "reason": reason.value,
                "url": f"/user/workflows/{schedule.workflow_id}",
            },
        )
    except Exception:  # pragma: no cover — best-effort
        logger.exception(
            "workflows._notify_schedule_owner_deactivated failed schedule=%s",
            schedule.id,
        )


async def get_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> WorkflowSchedule:
    """Single-row read — raises :class:`ScheduleNotFound` on miss so
    the router 404s cleanly (no info leak on cross-org)."""
    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None:
        raise ScheduleNotFound(f"schedule {schedule_id} not found in org {org_id}")
    return schedule


async def list_schedules_for_workflow_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> list[WorkflowSchedule]:
    """All schedules attached to a workflow, oldest-first. Cross-org
    guard: workflow must belong to ``org_id`` — else
    :class:`WorkflowNotFound` (router → 404)."""
    workflow = await _da.get_workflow(session, org_id=org_id, workflow_id=workflow_id)
    if workflow is None:
        raise WorkflowNotFound(f"workflow {workflow_id} not found in org {org_id}")
    return await _da.list_schedules_for_workflow(session, org_id=org_id, workflow_id=workflow_id)


def preview_next_fires_service(
    *,
    schedule_kind: ScheduleKind,
    config_json: dict[str, Any],
    timezone_name: str,
    starts_at: datetime,
    count: int = 5,
    now: datetime | None = None,
) -> list[datetime]:
    """Pure function — compute the next N fires for a candidate
    schedule config without persisting anything. Builder calls this
    on keystroke (debounced client-side) to render the "next 5 fires"
    preview.

    Runs the same validator + recurrence math the create path uses so
    the preview 422 matches the save 422. Not marked ``async`` because
    it never touches I/O; router awaits it via a no-op ``asyncio.run``
    is unnecessary — call directly."""
    now = now or datetime.now(UTC)
    # Preview endpoints usually accept "starts_at now" as a
    # convenience — the operator hasn't committed to a start date
    # yet. Skip the "past starts_at" rejection for the preview path;
    # everything else must validate.
    effective_starts_at = max(starts_at, now)
    _validate_config_and_bounds(
        schedule_kind=schedule_kind,
        config=config_json,
        starts_at=effective_starts_at,
        end_at=None,
        max_runs=None,
        tz_name=timezone_name,
        now=now,
    )

    # Build a synthetic in-memory schedule for iterative compute.
    ephemeral = WorkflowSchedule(
        name="_preview",
        schedule_kind=schedule_kind,
        config_json=config_json,
        timezone=timezone_name,
        starts_at=effective_starts_at,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=ConcurrencyPolicy.forbid,
    )
    fires: list[datetime] = []
    cursor = now
    for _ in range(count):
        try:
            nxt = compute_next_run_at(ephemeral, now=cursor)
        except (ScheduleValidationError, RecurrenceTimeout):
            break
        if not fires or nxt > fires[-1]:
            fires.append(nxt)
            # Feed forward: use the fire time as the anchor for the
            # next compute so we get 5 distinct future datetimes.
            cursor = nxt
            ephemeral.last_run_at = nxt
        else:
            break
    return fires


async def delete_schedule_service(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    schedule_id: uuid.UUID,
) -> None:
    """Hard delete. Router uses this from DELETE endpoint."""
    schedule = await _da.get_schedule_by_id_and_org(session, org_id=org_id, schedule_id=schedule_id)
    if schedule is None:
        raise ScheduleNotFound(f"schedule {schedule_id} not found in org {org_id}")

    await _da.delete_schedule(session, org_id=org_id, schedule_id=schedule_id)
    await session.commit()
    await log_entity_change(
        action="workflows.schedule_deleted",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
        before={
            "workflow_id": str(schedule.workflow_id),
            "name": schedule.name,
            "schedule_kind": schedule.schedule_kind.value,
        },
    )


# --- sweep dispatch ------------------------------------------------------


async def sweep_due_schedules(now: datetime | None = None) -> dict[str, int]:
    """Beat entry point (called from ``tasks.sweep_waits``). Two-phase:

      1. **Claim** — one session, ``SELECT ... FOR UPDATE SKIP LOCKED``
         to atomically pick due schedules and snapshot the fields the
         dispatch needs; commit + release the row locks.
      2. **Dispatch** — one fresh session per claimed schedule. The
         fresh session isolates ``engine.start_run``'s internal commit
         (which would otherwise invalidate a shared session's
         savepoint) and gives each dispatch clean transactional
         boundaries — a poison row can't roll back siblings.

    The two-phase pattern trades the SKIP-LOCKED lock's per-fire hold
    duration (now sub-millisecond, since we release before dispatch)
    for the ability to use the engine's existing commit semantics
    unchanged. Race window: two overlapping sweeps could double-fire
    a schedule; the ``trigger_event_id`` dedup + send_guard's
    per-recipient idempotency absorb this in practice.
    """
    from src.app.shared.db import async_session

    now = now or datetime.now(UTC)
    fired = 0
    skipped = 0
    errored = 0

    # Phase 1 — claim.
    async with async_session() as claim_sess:
        due_rows = await _da.select_due_schedules_for_update_skip_locked(
            claim_sess, now=now, limit=SWEEP_BATCH_SIZE
        )
        snapshots = [_ScheduleSnapshot.from_row(s) for s in due_rows]
        await claim_sess.commit()

    # Phase 2 — dispatch each in its own session.
    for snap in snapshots:
        try:
            outcome = await _dispatch_one(snap, now=now)
            if outcome == "fired":
                fired += 1
            else:
                skipped += 1
        except (ScheduleValidationError, RecurrenceTimeout) as exc:
            errored += 1
            await _deactivate_after_recurrence_error(snap.id, snap.org_id, exc)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "workflows.sweep_due_schedules dispatch_failed schedule=%s",
                snap.id,
            )
            errored += 1

    return {
        "found": len(snapshots),
        "fired": fired,
        "skipped": skipped,
        "errored": errored,
    }


class _ScheduleSnapshot:
    """Plain-data snapshot of the fields the dispatch needs, captured
    inside the claim transaction so the dispatch loop doesn't have to
    hold the SKIP-LOCKED row-lock while it fires. Not a dataclass —
    slots-only for a tiny memory footprint per sweep tick."""

    __slots__ = (
        "id",
        "org_id",
        "workflow_id",
        "contact_id",
        "schedule_kind",
        "config_json",
        "timezone",
        "starts_at",
        "end_at",
        "max_runs",
        "runs_completed",
        "last_run_at",
        "next_run_at",
        "on_missed",
        "concurrency_policy",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @classmethod
    def from_row(cls, row: WorkflowSchedule) -> _ScheduleSnapshot:
        return cls(
            id=row.id,
            org_id=row.org_id,
            workflow_id=row.workflow_id,
            contact_id=row.contact_id,
            schedule_kind=row.schedule_kind,
            config_json=dict(row.config_json or {}),
            timezone=row.timezone,
            starts_at=row.starts_at,
            end_at=row.end_at,
            max_runs=row.max_runs,
            runs_completed=row.runs_completed,
            last_run_at=row.last_run_at,
            next_run_at=row.next_run_at,
            on_missed=row.on_missed,
            concurrency_policy=row.concurrency_policy,
        )

    def to_ephemeral_schedule(self) -> WorkflowSchedule:
        """Materialize a detached ``WorkflowSchedule`` instance for
        ``compute_next_run_at`` (which reads schedule_kind + config +
        timezone + last_run_at). Not attached to any session — pure
        data holder."""
        wf = WorkflowSchedule(
            org_id=self.org_id,
            workflow_id=self.workflow_id,
            name="_snapshot",
            schedule_kind=self.schedule_kind,
            config_json=self.config_json,
            timezone=self.timezone,
            starts_at=self.starts_at,
            on_missed=self.on_missed,
            concurrency_policy=self.concurrency_policy,
        )
        wf.last_run_at = self.last_run_at
        wf.next_run_at = self.next_run_at
        wf.runs_completed = self.runs_completed or 0
        return wf


async def _dispatch_one(
    snap: _ScheduleSnapshot,
    *,
    now: datetime,
) -> Literal["fired", "skipped"]:
    """Fresh-session dispatch for one claimed schedule.

    The fresh session isolates ``engine.start_run``'s internal commit
    from the claim session. Each dispatch is its own transaction —
    poison rows can't roll back siblings; the engine's committing
    behaviour stays unchanged."""
    from src.app.shared.db import async_session

    async with async_session() as sess:
        return await _dispatch_due_schedule(sess, snap=snap, now=now)


async def _deactivate_after_recurrence_error(
    schedule_id: uuid.UUID,
    org_id: uuid.UUID,
    exc: Exception,
) -> None:
    """Best-effort deactivation outside the failing dispatch session.
    Opens its own transaction so a poison row's deactivation lands
    even when the dispatch txn rolled back."""
    from src.app.shared.db import async_session

    async with async_session() as sess:
        await _mark_schedule_deactivated_by_recurrence_error(
            sess, schedule_id=schedule_id, org_id=org_id, exc=exc
        )


async def _dispatch_due_schedule(
    session: AsyncSession,
    *,
    snap: _ScheduleSnapshot,
    now: datetime,
) -> Literal["fired", "skipped"]:
    """Fresh-session single-schedule dispatch.

    Sequence:
      1. Set the RLS org context so ``engine.start_run`` writes under
         the right tenant.
      2. Load the workflow (org-scoped) — 404 as a hard skip.
      3. ``concurrency_policy`` check: ``forbid`` skips if a prior
         run is still running.
      4. Per-org fire-budget check.
      5. Missed-fire count → audit event.
      6. Publish ``workflow.schedule_fired`` event (observability).
      7. Call ``engine.start_run`` with a server-generated UUID as
         ``trigger_event_id`` (never exposed to clients).
      8. Stamp run with schedule provenance.
      9. Advance ``next_run_at``, increment ``runs_completed``,
         evaluate terminal conditions.

    Note: ``engine.start_run`` internally commits the session. Steps
    8 + 9 run in a fresh implicit transaction after that commit;
    that's fine — the run row is already durable, and stamping /
    advancing are independent writes.
    """
    from sqlalchemy import update as _sql_update

    from src.app.core.events import bus as events_bus
    from src.app.core.events.event_catalog import WORKFLOW_SCHEDULE_FIRED
    from src.app.core.workflows import engine as workflows_engine
    from src.app.core.workflows.models import WorkflowRun

    # 1. RLS org context per dispatch (sweep runs cross-org).
    await _da.set_current_org_context(session, org_id=snap.org_id)

    # 2. Load workflow. Cross-org / archived should already be filtered
    # by the sweep query, but defensive.
    workflow = await _da.get_workflow(session, org_id=snap.org_id, workflow_id=snap.workflow_id)
    if workflow is None or workflow.status != WorkflowStatus.active:
        await _advance_schedule(session, snap=snap, now=now, outcome="skipped")
        await session.commit()
        return "skipped"

    # 3. Concurrency policy.
    if snap.concurrency_policy == ConcurrencyPolicy.forbid:
        prior = await _da.find_existing_run(
            session,
            workflow_id=snap.workflow_id,
            contact_id=snap.contact_id,
        )
        if prior is not None and prior.status == WorkflowRunStatus.running:
            logger.info(
                "workflows.sweep concurrency_forbid_skip schedule=%s prior_run=%s",
                snap.id,
                prior.id,
            )
            await _advance_schedule(session, snap=snap, now=now, outcome="skipped")
            await session.commit()
            return "skipped"
    elif snap.concurrency_policy == ConcurrencyPolicy.replace:
        prior = await _da.find_existing_run(
            session,
            workflow_id=snap.workflow_id,
            contact_id=snap.contact_id,
        )
        if prior is not None and prior.status == WorkflowRunStatus.running:
            prior.status = WorkflowRunStatus.canceled
            await session.flush()

    # 4. Per-org fire-budget.
    hour_start = now - timedelta(hours=1)
    recent = await _da.count_recent_workflow_runs_for_org(
        session, org_id=snap.org_id, since=hour_start
    )
    if recent >= MAX_FIRES_PER_HOUR_PER_ORG:
        logger.warning(
            "workflows.sweep rate_limited org=%s schedule=%s recent=%d cap=%d",
            snap.org_id,
            snap.id,
            recent,
            MAX_FIRES_PER_HOUR_PER_ORG,
        )
        # Do NOT advance next_run_at — try again next tick.
        return "skipped"

    # 5. Missed-fire audit (only meaningful when we're late).
    if snap.next_run_at and snap.next_run_at < now - timedelta(minutes=1):
        missed = _count_missed_fires_snap(snap, now=now)
        if missed >= 1:
            logger.info(
                "workflows.sweep missed_fires schedule=%s count=%d policy=%s",
                snap.id,
                missed,
                snap.on_missed.value,
            )
            await log_entity_change(
                action="workflows.schedule_missed_fire",
                entity_type="workflow_schedule",
                entity_id=snap.id,
                after={"missed_count": missed, "policy": snap.on_missed.value},
            )

    # 6 + 7. Emit observability event + fire the run.
    trigger_event_id = str(uuid.uuid4())
    try:
        await events_bus.publish(
            WORKFLOW_SCHEDULE_FIRED,
            {
                "workflow_id": str(snap.workflow_id),
                "schedule_id": str(snap.id),
                "schedule_run_uuid": trigger_event_id,
                "contact_id": str(snap.contact_id) if snap.contact_id else None,
            },
            org_id=snap.org_id,
            event_id=trigger_event_id,
        )
    except Exception:
        logger.exception("workflows.sweep event_publish_failed schedule=%s", snap.id)
        # Publish failure is non-fatal — the run still fires.

    run = await workflows_engine.start_run(
        session,
        workflow=workflow,
        contact_id=snap.contact_id,
        trigger_event_id=trigger_event_id,
        trigger_payload={
            "schedule_id": str(snap.id),
            "schedule_kind": snap.schedule_kind.value,
            "schedule_run_uuid": trigger_event_id,
        },
    )
    # 8. Stamp the run with schedule provenance. engine.start_run
    # committed, so this is a fresh transaction — SET LOCAL is
    # re-issued because Postgres scopes it to the current
    # transaction.
    await _da.set_current_org_context(session, org_id=snap.org_id)
    await session.execute(
        _sql_update(WorkflowRun)
        .where(WorkflowRun.id == run.id)
        .values(
            trigger_kind=TriggerKind.schedule,
            trigger_source_id=snap.id,
        )
    )

    # 9. Advance state.
    await _advance_schedule(session, snap=snap, now=now, outcome="fired")
    await session.commit()
    return "fired"


async def _advance_schedule(
    session: AsyncSession,
    *,
    snap: _ScheduleSnapshot,
    now: datetime,
    outcome: Literal["fired", "skipped"],
) -> None:
    """Advance ``next_run_at`` / ``runs_completed`` / ``last_run_at``
    and evaluate terminal conditions. When terminal, deactivates
    the schedule with the right reason. Does NOT commit — caller
    owns the transaction boundary."""
    fields: dict[str, Any] = {}
    if outcome == "fired":
        snap.last_run_at = now
        snap.runs_completed = (snap.runs_completed or 0) + 1
        fields["last_run_at"] = now
        fields["runs_completed"] = snap.runs_completed

    # Terminal conditions before recomputing next_run_at.
    terminated_reason: DeactivationReason | None = None
    if snap.max_runs is not None and snap.runs_completed >= snap.max_runs:
        terminated_reason = DeactivationReason.max_runs
    elif snap.end_at is not None and now >= snap.end_at:
        terminated_reason = DeactivationReason.end_at
    elif snap.schedule_kind == ScheduleKind.once and outcome == "fired":
        terminated_reason = DeactivationReason.ended

    if terminated_reason is not None:
        fields["active"] = False
        fields["deactivation_reason"] = terminated_reason
        fields["next_run_at"] = None
    else:
        # Recompute from the freshly-updated snapshot state.
        preview = snap.to_ephemeral_schedule()
        fields["next_run_at"] = compute_next_run_at(preview, now=now)

    await _da.update_schedule_fields(
        session,
        org_id=snap.org_id,
        schedule_id=snap.id,
        fields=fields,
    )


async def _mark_schedule_deactivated_by_recurrence_error(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    org_id: uuid.UUID,
    exc: Exception,
) -> None:
    """Called by the sweep when a schedule's recurrence math raised
    or timed out. Deactivates the row + writes a distinctive audit
    event so operators see the misconfigured row."""
    reason = (
        DeactivationReason.recurrence_timeout
        if isinstance(exc, RecurrenceTimeout)
        else DeactivationReason.recurrence_invalid
    )
    await _da.update_schedule_fields(
        session,
        org_id=org_id,
        schedule_id=schedule_id,
        fields={
            "active": False,
            "deactivation_reason": reason,
            "next_run_at": None,
        },
    )
    await session.commit()
    logger.warning(
        "workflows.sweep schedule_deactivated_by_error schedule=%s reason=%s exc=%s",
        schedule_id,
        reason.value,
        exc,
    )
    await log_entity_change(
        action="workflows.schedule_auto_deactivated",
        entity_type="workflow_schedule",
        entity_id=schedule_id,
        after={"reason": reason.value, "error": str(exc)},
    )


def _count_missed_fires_snap(snap: _ScheduleSnapshot | WorkflowSchedule, *, now: datetime) -> int:
    """How many additional fires would have landed between the
    scheduled ``next_run_at`` and ``now``? Best-effort — for cron
    we don't walk the expression (could be pathological), just count
    based on the schedule kind's natural cadence.

    Accepts either a :class:`_ScheduleSnapshot` (sweep call site) or
    a full :class:`WorkflowSchedule` (test call site). Both expose
    the same attribute names."""
    if snap.next_run_at is None or snap.next_run_at >= now:
        return 0
    delta = now - snap.next_run_at
    kind = snap.schedule_kind
    if kind == ScheduleKind.interval:
        config = snap.config_json or {}
        unit = config.get("unit")
        every = int(config.get("every") or 1)
        seconds = every * {"minutes": 60, "hours": 3600, "days": 86400}.get(unit, 60)
        return int(delta.total_seconds() // seconds)
    if kind == ScheduleKind.daily:
        return int(delta.total_seconds() // 86400)
    if kind == ScheduleKind.weekly:
        return int(delta.total_seconds() // (86400 * 7))
    if kind == ScheduleKind.monthly:
        return int(delta.total_seconds() // (86400 * 30))
    # once + cron — treat as "at least one missed" without further math.
    return 1


# --- small helpers -------------------------------------------------------


def _isoformat_no_micros(dt: datetime) -> str:
    """ETag string — second-precision UTC ISO so client + server
    always round-trip identically. Normalizes tz to UTC and STRIPS
    the tz suffix so a client that sends the ISO without ``+00:00``
    (common when browsers proxy the header verbatim through a
    ``split('.')[0]``-style shortcut) still matches. Any tz-aware
    input is first converted to UTC; naive inputs are assumed UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.replace(microsecond=0, tzinfo=None).isoformat()


def _to_json_safe(value: Any) -> Any:
    """Coerce enums / datetimes into JSON-friendly primitives for
    audit ``after`` snapshots."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


__all__ = [
    "CONSECUTIVE_EMPTY_DEACTIVATION_THRESHOLD",
    "MAX_ACTIVE_SCHEDULES_PER_ORG",
    "MAX_FIRES_PER_HOUR_PER_ORG",
    "MAX_SCHEDULE_HORIZON_YEARS",
    "MIN_INTER_FIRE_MINUTES",
    "ScheduleCapExceeded",
    "ScheduleNotFound",
    "ScheduleValidationError",
    "archive_workflow",
    "cascade_schedules_on_contact_delete",
    "change_status",
    "compute_next_run_at",
    "create_folder",
    "create_schedule_service",
    "create_workflow",
    "deactivate_schedule_for_empty_fires",
    "delete_folder",
    "delete_schedule_service",
    "get_schedule_service",
    "increment_consecutive_empty_fires_service",
    "list_schedules_for_workflow_service",
    "preview_next_fires_service",
    "reap_orphaned_pending_runs",
    "reset_consecutive_empty_fires_service",
    "sweep_orphan_schedules",
    "export_workflow",
    "get_ab_stats",
    "get_workflow",
    "get_workflow_version",
    "import_workflow",
    "list_custom_event_types_for_picker",
    "list_folders",
    "list_workflow_versions",
    "list_workflows",
    "list_workflows_with_schedule_summary",
    "pair_for_ab",
    "patch_folder",
    "pause_schedule_service",
    "resume_schedule_service",
    "rollback_workflow",
    "sweep_due_schedules",
    "unpair_ab",
    "update_enabled_event_types_from_graph",
    "update_schedule_service",
    "update_workflow",
]
