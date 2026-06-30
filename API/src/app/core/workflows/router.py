"""HTTP routes for the workflows module.

Twelve endpoints under ``/api/v1/workflows`` — CRUD, status
transitions, folder CRUD, clone. Engine + run-history endpoints
land in Step 4; analytics + diagnostics in Step 19; trigger
subscription is internal (Step 5).

Standard exception → HTTP mapping (see :func:`_workflow_http_map`):

  * :class:`WorkflowNotFound`        → 404
  * :class:`DuplicateWorkflowName`   → 409
  * :class:`WorkflowLocked`          → 409
  * :class:`FolderHasWorkflows`      → 409 (carries ``count``)
  * :class:`InvalidGraph`            → 422 (carries ``reason``)
  * :class:`ActivationBlocked`       → 409 (carries ``reason``)
  * ``ValueError`` (invalid transition)  → 409

The router never executes SQL directly — every read + write goes
through :mod:`core.workflows.service` (manager spec 2026-06-25:
"router never imports another module's DAL").
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.users.models import User
from src.app.core.workflows import engine as workflows_engine
from src.app.core.workflows import service as workflows_service
from src.app.core.workflows import templates_gallery
from src.app.core.workflows.exceptions import (
    ActivationBlocked,
    DuplicateWorkflowName,
    FolderHasWorkflows,
    InvalidGraph,
    WorkflowError,
    WorkflowLocked,
    WorkflowNotFound,
)
from src.app.core.workflows.models import WorkflowRunStatus, WorkflowStatus
from src.app.core.workflows.permissions import (
    PERM_ACTIVATE,
    PERM_CLONE,
    PERM_READ,
    PERM_WRITE,
)
from src.app.core.workflows.schemas import (
    RollbackRequest,
    WorkflowCreate,
    WorkflowExport,
    WorkflowFolderCreate,
    WorkflowFolderRead,
    WorkflowImportRequest,
    WorkflowRead,
    WorkflowRunRead,
    WorkflowStepRunRead,
    WorkflowUpdate,
    WorkflowVersionDetailRead,
    WorkflowVersionListResponse,
    WorkflowVersionSummaryRead,
)
from src.app.core.workflows import data_access as _workflows_da
from src.app.shared.context import get_context
from src.app.shared.db import get_db


router = APIRouter(prefix="/workflows", tags=["Workflows"])


# --- helpers -------------------------------------------------------------


def _workflow_http_map(exc: WorkflowError) -> HTTPException:
    """Translate workflow domain exceptions into FastAPI
    HTTPException with the canonical status code per the Step-3
    spec. Carries ``reason`` for InvalidGraph + ActivationBlocked
    so the editor can render the specific failure mode."""
    if isinstance(exc, WorkflowNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workflow not found",
        )
    if isinstance(exc, DuplicateWorkflowName):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    if isinstance(exc, WorkflowLocked):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    if isinstance(exc, FolderHasWorkflows):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "folder_has_workflows",
                "message": str(exc),
                "count": exc.count,
            },
        )
    if isinstance(exc, InvalidGraph):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_graph",
                "reason": exc.reason,
            },
        )
    if isinstance(exc, ActivationBlocked):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "activation_blocked",
                "reason": exc.reason,
            },
        )
    # Generic catch-all (subclasses of WorkflowError we forgot to
    # special-case land here as 422 with the message verbatim).
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


def _require_org_id() -> uuid.UUID:
    """Read the active request's org_id off the request context.
    Behind ``require_permissions`` it's guaranteed populated, but
    we 400 defensively rather than crash if the middleware skipped."""
    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )
    return ctx.org_id


class _CloneBody(BaseModel):
    """POST body for ``/workflows/{id}/clone``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)


class _FolderPatchBody(BaseModel):
    """PATCH body for ``/workflows/folders/{id}`` — every field
    optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_folder_id: uuid.UUID | None = None
    display_order: int | None = Field(default=None, ge=0)


# --- folder endpoints (mounted FIRST so '/workflows/folders'
# doesn't get swallowed by the '/workflows/{id}' path) ---------------------


@router.get(
    "/folders",
    response_model=list[WorkflowFolderRead],
)
async def list_folders_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> list[WorkflowFolderRead]:
    org_id = _require_org_id()
    rows = await workflows_service.list_folders(db, org_id=org_id)
    return [WorkflowFolderRead.model_validate(r) for r in rows]


@router.post(
    "/folders",
    response_model=WorkflowFolderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder_endpoint(
    payload: WorkflowFolderCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_WRITE)),
) -> WorkflowFolderRead:
    org_id = _require_org_id()
    folder = await workflows_service.create_folder(
        db, org_id=org_id, payload=payload
    )
    return WorkflowFolderRead.model_validate(folder)


@router.patch(
    "/folders/{folder_id}",
    response_model=WorkflowFolderRead,
)
async def patch_folder_endpoint(
    folder_id: uuid.UUID,
    payload: _FolderPatchBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_WRITE)),
) -> WorkflowFolderRead:
    org_id = _require_org_id()
    try:
        folder = await workflows_service.patch_folder(
            db,
            org_id=org_id,
            folder_id=folder_id,
            name=payload.name,
            parent_folder_id=payload.parent_folder_id,
            display_order=payload.display_order,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowFolderRead.model_validate(folder)


@router.delete(
    "/folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_folder_endpoint(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    org_id = _require_org_id()
    try:
        await workflows_service.delete_folder(
            db, org_id=org_id, folder_id=folder_id
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- run-history endpoints (Step 4) --------------------------------------
# Mounted BEFORE /{workflow_id} so '/workflows/runs/{run_id}' doesn't get
# swallowed by the UUID matcher on the workflow-detail route.


class WorkflowRunListOut(BaseModel):
    """Paginated run-history envelope."""

    items: list[WorkflowRunRead]
    total: int


@router.get(
    "/runs/{run_id}",
    response_model=WorkflowRunRead,
)
async def get_run_endpoint(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> WorkflowRunRead:
    """Single-row hydrate for the run-detail drawer."""
    org_id = _require_org_id()
    run = await _workflows_da.get_run(db, org_id=org_id, run_id=run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    return WorkflowRunRead.model_validate(run)


@router.get(
    "/runs/{run_id}/steps",
    response_model=list[WorkflowStepRunRead],
)
async def list_run_steps_endpoint(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> list[WorkflowStepRunRead]:
    """Ordered step timeline for one run — drives Step 19's
    per-run drill-down."""
    org_id = _require_org_id()
    # 404 the steps endpoint if the parent run doesn't exist so the
    # UI doesn't render an empty drawer.
    run = await _workflows_da.get_run(db, org_id=org_id, run_id=run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    rows = await _workflows_da.list_step_runs(
        db, org_id=org_id, run_id=run_id
    )
    return [WorkflowStepRunRead.model_validate(r) for r in rows]


# --- workflow CRUD --------------------------------------------------------


class WorkflowListOut(BaseModel):
    """Paginated list envelope."""

    items: list[WorkflowRead]
    total: int


@router.get(
    "",
    response_model=WorkflowListOut,
)
async def list_workflows_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    folder_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> WorkflowListOut:
    org_id = _require_org_id()
    status_enum: WorkflowStatus | None = None
    if status_filter is not None:
        try:
            status_enum = WorkflowStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid status filter '{status_filter}'",
            ) from exc

    rows, total = await workflows_service.list_workflows(
        db,
        org_id=org_id,
        status=status_enum,
        category=category,
        folder_id=folder_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return WorkflowListOut(
        items=[WorkflowRead.model_validate(r) for r in rows],
        total=total,
    )


@router.post(
    "",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_endpoint(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> WorkflowRead:
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.create_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            payload=payload,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/{workflow_id}",
    response_model=WorkflowRead,
)
async def get_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> WorkflowRead:
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.get_workflow(
            db, org_id=org_id, workflow_id=workflow_id
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/{workflow_id}/runs",
    response_model=WorkflowRunListOut,
)
async def list_workflow_runs_endpoint(
    workflow_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    contact_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_READ)),
) -> WorkflowRunListOut:
    """Paginated run list for one workflow. Drives the Step-19
    analytics + run-history list. Filter by status + contact_id."""
    org_id = _require_org_id()
    run_status: WorkflowRunStatus | None = None
    if status_filter is not None:
        try:
            run_status = WorkflowRunStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid run status '{status_filter}'",
            ) from exc

    rows, total = await _workflows_da.list_runs(
        db,
        org_id=org_id,
        workflow_id=workflow_id,
        contact_id=contact_id,
        status=run_status,
        limit=limit,
        offset=offset,
    )
    return WorkflowRunListOut(
        items=[WorkflowRunRead.model_validate(r) for r in rows],
        total=total,
    )


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowRead,
)
async def patch_workflow_endpoint(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> WorkflowRead:
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.update_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
            payload=payload,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    except ValueError as exc:
        # Invalid status transition (state-machine reject).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowRead.model_validate(workflow)


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    """Soft-archive — never hard delete. Outstanding runs continue
    under the archived version."""
    org_id = _require_org_id()
    try:
        await workflows_service.archive_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- status transitions ---------------------------------------------------


@router.post(
    "/{workflow_id}/activate",
    response_model=WorkflowRead,
)
async def activate_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_ACTIVATE)),
) -> WorkflowRead:
    """Flip a workflow to ``status='active'``. Re-runs the graph
    validator so a broken draft can't go live."""
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.change_status(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
            new_status=WorkflowStatus.active,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowRead.model_validate(workflow)


@router.post(
    "/{workflow_id}/pause",
    response_model=WorkflowRead,
)
async def pause_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_ACTIVATE)),
) -> WorkflowRead:
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.change_status(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
            new_status=WorkflowStatus.paused,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowRead.model_validate(workflow)


@router.post(
    "/{workflow_id}/archive",
    response_model=WorkflowRead,
)
async def archive_workflow_endpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> WorkflowRead:
    org_id = _require_org_id()
    try:
        workflow = await workflows_service.archive_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(workflow)


# --- clone ----------------------------------------------------------------


@router.post(
    "/{workflow_id}/clone",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_workflow_endpoint(
    workflow_id: uuid.UUID,
    payload: _CloneBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_CLONE)),
) -> WorkflowRead:
    """Clone an existing workflow as a fresh draft. Copies the
    graph + the user-tunable scalar fields; the new row gets
    ``status='draft'``, ``current_version=1``, and a fresh v1
    version row in ``tbl_workflow_versions``."""
    from src.app.core.workflows.schemas import WorkflowGraph

    org_id = _require_org_id()
    try:
        source = await workflows_service.get_workflow(
            db, org_id=org_id, workflow_id=workflow_id
        )
        new_payload = WorkflowCreate(
            name=payload.name,
            description=source.description,
            category=source.category,
            folder_id=source.folder_id,
            is_marketing=source.is_marketing,
            re_enrollment_rule=(
                source.re_enrollment_rule.value
                if hasattr(source.re_enrollment_rule, "value")
                else str(source.re_enrollment_rule)
            ),
            graph=WorkflowGraph.model_validate(source.graph),
            goal_node_id=source.goal_node_id,
            cost_per_run_cents=source.cost_per_run_cents,
        )
        clone = await workflows_service.create_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            payload=new_payload,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(clone)


# --- Step 14: test-fire (dry-run preview) ------------------------------


class WorkflowTestFireRequest(BaseModel):
    """Operator-supplied event seed for the dry-run. All fields are
    optional — the engine doesn't actually consult them in v1 (the
    dry walk picks the first outbound edge at every fork), but the
    shape is stable so Step 19 can extend it with explicit branch
    overrides without a frontend change."""

    model_config = ConfigDict(extra="forbid")

    event_type: str | None = Field(default=None, max_length=120)
    contact_id: uuid.UUID | None = Field(default=None)
    payload: dict | None = Field(default=None)


class WorkflowTestFireStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    node_type: str
    edge_label: str | None = None
    skip_reason: str | None = None


class WorkflowTestFireResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    steps: list[WorkflowTestFireStepRead]
    outcome: str
    error: str | None = None


@router.post(
    "/{workflow_id}/test-fire",
    response_model=WorkflowTestFireResponse,
)
async def test_fire_workflow_endpoint(
    workflow_id: uuid.UUID,
    payload: WorkflowTestFireRequest,
    user: User = Depends(require_permissions(PERM_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowTestFireResponse:
    """Synthetic dry-run of a workflow — useful for the canvas
    operator to preview what would happen before they activate.

    Walks the graph from the trigger node in memory, recording each
    node visit, the edge it would follow, and the eventual outcome.
    No ``tbl_workflow_runs`` / ``tbl_workflow_step_runs`` rows land,
    no adapter is called, no external IO. Gated on ``workflows.write``
    because the trace can leak workflow topology.
    """
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        workflow = await workflows_service.get_workflow(
            db, org_id=org_id, workflow_id=workflow_id
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc

    try:
        result = await workflows_engine.start_run(
            db,
            workflow=workflow,
            contact_id=payload.contact_id,
            trigger_event_id=None,
            trigger_payload=payload.payload or {},
            dry_run=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return WorkflowTestFireResponse.model_validate(result)


# --- Step 16: templates gallery + clone-from-gallery -------------------


class WorkflowGalleryEntryRead(BaseModel):
    """Serialised gallery template. The ``graph_preview`` field is a
    full workflow-graph dict (same shape as
    ``WorkflowRead.graph``) so the frontend canvas component can
    render it directly in read-only mode."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    category: str
    channels: list[str]
    goal_node_label: str
    est_setup_time_minutes: int
    est_completion_rate_pct: int
    screenshot_url: str | None = None
    graph_preview: dict
    is_marketing: bool
    re_enrollment_rule: str


class WorkflowGalleryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[WorkflowGalleryEntryRead]
    total: int


class WorkflowGalleryCloneRequest(BaseModel):
    """Operator-supplied overrides for the cloned workflow."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    folder_id: uuid.UUID | None = Field(default=None)


@router.get("/gallery", response_model=WorkflowGalleryListResponse)
async def list_workflow_gallery_endpoint(
    _user: User = Depends(require_permissions(PERM_READ)),
) -> WorkflowGalleryListResponse:
    """Return the static gallery catalogue. Org-agnostic — every org
    sees the same 15 templates plus any pack-registered entries
    (Layer 2; not present in v1)."""
    entries = templates_gallery.list_gallery()
    return WorkflowGalleryListResponse(
        items=[WorkflowGalleryEntryRead.model_validate(e) for e in entries],
        total=len(entries),
    )


@router.post(
    "/gallery/{template_id}/clone",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_workflow_from_gallery_endpoint(
    template_id: str,
    payload: WorkflowGalleryCloneRequest,
    user: User = Depends(require_permissions(PERM_CLONE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    """Clone the named gallery template into the caller's org as a
    new draft workflow. Send-action nodes land with their
    ``template_id`` stripped — the Step-15 editor's validation
    markers prompt the operator to pick a real template per node
    before activating."""
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        clone = await templates_gallery.clone_from_gallery(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            template_id=template_id,
            name=payload.name,
            folder_id=payload.folder_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"gallery template '{exc.args[0]}' not found",
        ) from exc
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(clone)


# --- Step 17: version history + rollback + import / export -----------


@router.get(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionListResponse,
)
async def list_workflow_versions_endpoint(
    workflow_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(require_permissions(PERM_READ)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowVersionListResponse:
    """Paginated version history (newest first) for one workflow.

    Each entry carries only the summary metadata
    (``version`` / ``change_note`` / ``created_by_user_id`` /
    ``created_at``); the full graph for "View" is fetched via
    :func:`get_workflow_version_endpoint`.
    """
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        rows, total = await workflows_service.list_workflow_versions(
            db,
            org_id=org_id,
            workflow_id=workflow_id,
            limit=limit,
            offset=offset,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowVersionListResponse(
        items=[WorkflowVersionSummaryRead.model_validate(r) for r in rows],
        total=total,
    )


@router.get(
    "/{workflow_id}/versions/{version}",
    response_model=WorkflowVersionDetailRead,
)
async def get_workflow_version_endpoint(
    workflow_id: uuid.UUID,
    version: int,
    _user: User = Depends(require_permissions(PERM_READ)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowVersionDetailRead:
    """Full graph + metadata for one historical version. Drives the
    canvas page's read-only "View" overlay."""
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        row = await workflows_service.get_workflow_version(
            db,
            org_id=org_id,
            workflow_id=workflow_id,
            version=version,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowVersionDetailRead.model_validate(row)


@router.post(
    "/{workflow_id}/rollback",
    response_model=WorkflowRead,
)
async def rollback_workflow_endpoint(
    workflow_id: uuid.UUID,
    payload: RollbackRequest,
    user: User = Depends(require_permissions(PERM_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    """Copy the target version's graph into the live workflow as a
    NEW version (preserves the audit chain). Refused on active
    marketing workflows — same lock as ``PATCH /workflows/{id}``."""
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        workflow = await workflows_service.rollback_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            workflow_id=workflow_id,
            target_version=payload.target_version,
            change_note=payload.change_note,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/{workflow_id}/export",
    response_model=WorkflowExport,
)
async def export_workflow_endpoint(
    workflow_id: uuid.UUID,
    _user: User = Depends(require_permissions(PERM_READ)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExport:
    """Portable JSON export for the canvas page's "Export JSON"
    button. The operator's browser downloads the response as
    ``<workflow-name>.workflow.json``."""
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    try:
        body = await workflows_service.export_workflow(
            db, org_id=org_id, workflow_id=workflow_id
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowExport.model_validate(body)


@router.post(
    "/import",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_workflow_endpoint(
    payload: WorkflowImportRequest,
    user: User = Depends(require_permissions(PERM_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    """Create a draft workflow from a previously-exported JSON body.
    Unknown ``template_id`` references on send + record.create_*
    nodes are remapped to ``null`` + stamped ``__valid=false`` so
    the Step-15 editor surfaces them. Name collisions auto-suffix
    `(2)` / `(3)` / …"""
    ctx = get_context()
    org_id = ctx.org_id if ctx is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no org context",
        )
    # Translate the import payload's `WorkflowExport` body into a
    # `WorkflowCreate` shape the service layer consumes.
    body = payload.json_body
    create_payload = WorkflowCreate(
        name=body.name,
        description=body.description,
        category=body.category,
        folder_id=payload.target_folder_id,
        is_marketing=body.is_marketing,
        re_enrollment_rule=body.re_enrollment_rule,
        graph=body.graph,
        goal_node_id=body.goal_node_id,
        cost_per_run_cents=body.cost_per_run_cents,
    )
    try:
        workflow = await workflows_service.import_workflow(
            db,
            org_id=org_id,
            user_id=getattr(user, "legacy_uuid", None),
            payload=create_payload,
            target_folder_id=payload.target_folder_id,
            override_name=payload.name,
        )
    except WorkflowError as exc:
        raise _workflow_http_map(exc) from exc
    return WorkflowRead.model_validate(workflow)


__all__ = ["router"]
