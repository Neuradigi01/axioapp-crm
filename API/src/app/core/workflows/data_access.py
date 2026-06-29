"""Data-access layer for the workflows module — single-file per
the locked layered convention (manager spec 2026-06-25).

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``. Step 2 fills in the
trigger CRUD + folder reads; Steps 4 / 5 will extend with run
helpers (insert_run + pending-sweep paginate + matcher lookup).

Tenant scoping is applied automatically by the ``do_orm_execute``
listener (``Workflow`` / ``WorkflowFolder`` inherit
``TenantScoped``); consumers still pass ``org_id`` explicitly so
Celery tasks + scripts without a context get correct results.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.models import (
    Workflow,
    WorkflowFolder,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowVersion,
)


# --- workflow reads ------------------------------------------------------


async def get_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> Workflow | None:
    """Single-row read by PK + org. ``None`` on miss or
    cross-tenant — callers map to :class:`WorkflowNotFound`."""
    result = await session.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_workflow_by_name(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
) -> Workflow | None:
    """Case-insensitive name lookup — drives the duplicate-name
    rejection on create + update. Uses the functional unique
    index ``uq_workflows_org_lower_name`` from migration 0136."""
    result = await session.execute(
        select(Workflow).where(
            Workflow.org_id == org_id,
            func.lower(Workflow.name) == name.strip().lower(),
        )
    )
    return result.scalar_one_or_none()


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
    """Filterable + paginated list. ``q`` matches against
    ``name`` + ``description`` (case-insensitive partial). The
    list page (Step 13) drives every filter from this single
    endpoint."""
    base = select(Workflow).where(Workflow.org_id == org_id)

    if status is not None:
        base = base.where(Workflow.status == status)
    if category is not None:
        base = base.where(Workflow.category == category)
    if folder_id is not None:
        base = base.where(Workflow.folder_id == folder_id)
    if q is not None and q.strip():
        like = f"%{q.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(Workflow.name).like(like),
                func.lower(func.coalesce(Workflow.description, "")).like(like),
            )
        )

    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(Workflow.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def count_workflows_in_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> int:
    """How many non-archived workflows still reference a folder —
    the service uses this to refuse folder deletion when the
    folder isn't empty."""
    result = await session.execute(
        select(func.count(Workflow.id)).where(
            Workflow.org_id == org_id,
            Workflow.folder_id == folder_id,
            Workflow.status != WorkflowStatus.archived,
        )
    )
    return int(result.scalar_one())


# --- folder reads --------------------------------------------------------


async def get_folder(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> WorkflowFolder | None:
    result = await session.execute(
        select(WorkflowFolder).where(
            WorkflowFolder.id == folder_id,
            WorkflowFolder.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_folders(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[WorkflowFolder]:
    """All folders for the org, ordered by ``display_order`` ASC
    then ``name`` ASC. Step 13's tree view sorts on render but the
    DAL's default order is the operator's chosen sort."""
    result = await session.execute(
        select(WorkflowFolder)
        .where(WorkflowFolder.org_id == org_id)
        .order_by(
            WorkflowFolder.display_order.asc(),
            WorkflowFolder.name.asc(),
        )
    )
    return list(result.scalars().all())


# --- version reads ------------------------------------------------------


async def list_versions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> list[WorkflowVersion]:
    """Append-only version history, newest first. Step 17's UI
    surfaces this for diff/revert."""
    result = await session.execute(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.org_id == org_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .order_by(WorkflowVersion.version.desc())
    )
    return list(result.scalars().all())


# --- stage-only writes (caller commits) --------------------------------


def add_workflow(session: AsyncSession, workflow: Workflow) -> Workflow:
    """Register a new Workflow for INSERT. Caller commits."""
    session.add(workflow)
    return workflow


def add_version(
    session: AsyncSession, version: WorkflowVersion
) -> WorkflowVersion:
    """Register a new WorkflowVersion for INSERT. Caller commits."""
    session.add(version)
    return version


def add_folder(
    session: AsyncSession, folder: WorkflowFolder
) -> WorkflowFolder:
    """Register a new WorkflowFolder for INSERT. Caller commits."""
    session.add(folder)
    return folder


async def delete_folder(
    session: AsyncSession, folder: WorkflowFolder
) -> None:
    """Hard delete on a folder row. Caller commits. Service checks
    ``count_workflows_in_folder`` first + raises 409 when non-empty."""
    await session.delete(folder)


# --- run helpers (Step 4) ----------------------------------------------


def insert_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    """Stage a new WorkflowRun for INSERT. Caller commits."""
    session.add(run)
    return run


def insert_step_run(
    session: AsyncSession, step_run: WorkflowStepRun
) -> WorkflowStepRun:
    """Stage a new WorkflowStepRun for INSERT. Caller commits."""
    session.add(step_run)
    return step_run


async def get_run_unscoped(
    session: AsyncSession, *, run_id: uuid.UUID
) -> WorkflowRun | None:
    """Cross-tenant single-row read by PK. The Celery worker calls
    this BEFORE setting ``RequestContext.org_id`` — once it has
    the run, it reads ``run.org_id`` and sets the context for the
    rest of the dispatch."""
    result = await session.execute(
        select(WorkflowRun).where(WorkflowRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def get_run_for_processing(
    session: AsyncSession, *, run_id: uuid.UUID
) -> WorkflowRun | None:
    """Locked single-row read used by the Celery step processor.
    Acquires a row-level lock via ``SELECT ... FOR UPDATE SKIP
    LOCKED`` so two concurrent workers can't process the same run
    in parallel — the loser gets ``None`` + bails out cleanly.

    Caller's transaction holds the lock until commit / rollback.
    """
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_runs_due_for_resume(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> list[WorkflowRun]:
    """``WHERE status='pending' AND next_step_at <= now()`` for the
    Celery beat sweep that resumes parked wait-nodes. Backed by the
    partial index ``ix_workflow_runs_pending_sweep`` from migration
    0136 so the scan stays cheap even at million-run scale."""
    stmt = (
        select(WorkflowRun)
        .where(
            WorkflowRun.status == WorkflowRunStatus.pending,
            WorkflowRun.next_step_at.is_not(None),
            WorkflowRun.next_step_at <= now,
        )
        .order_by(WorkflowRun.next_step_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_runs(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    status: WorkflowRunStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[WorkflowRun], int]:
    """Paginated run history. Drives the Step-19 analytics +
    diagnostics views; the per-workflow + per-contact filters cover
    "what fired" + "what fired for this contact" surface."""
    base = select(WorkflowRun).where(WorkflowRun.org_id == org_id)

    if workflow_id is not None:
        base = base.where(WorkflowRun.workflow_id == workflow_id)
    if contact_id is not None:
        base = base.where(WorkflowRun.contact_id == contact_id)
    if status is not None:
        base = base.where(WorkflowRun.status == status)

    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(WorkflowRun.started_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> WorkflowRun | None:
    """Tenant-scoped single-row read used by the
    ``GET /workflows/runs/{run_id}`` endpoint."""
    result = await session.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_step_runs(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[WorkflowStepRun]:
    """Append-only step timeline for one run, ordered by
    ``step_index`` ASC. Step 19's per-run drill-down shows this as
    the executed-step list."""
    result = await session.execute(
        select(WorkflowStepRun)
        .where(
            WorkflowStepRun.org_id == org_id,
            WorkflowStepRun.run_id == run_id,
        )
        .order_by(WorkflowStepRun.step_index.asc())
    )
    return list(result.scalars().all())


async def list_active_workflows_for_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
) -> list[Workflow]:
    """Matcher query — every ``active`` workflow in ``org_id`` whose
    trigger node listens on ``event_type``. Hits the GIN index
    ``ix_workflows_event_types_gin`` on
    ``tbl_workflows.enabled_event_types`` so the array filter
    stays cheap even with hundreds of workflows per org.

    The denormalised ``enabled_event_types`` column is maintained
    by the service layer (``update_enabled_event_types_from_graph``)
    so the matcher never has to walk the JSONB ``graph`` payload.
    """
    stmt = (
        select(Workflow)
        .where(Workflow.org_id == org_id)
        .where(Workflow.status == WorkflowStatus.active)
        .where(Workflow.enabled_event_types.any(event_type))
    )
    return list((await session.execute(stmt)).scalars().all())


async def find_existing_run(
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    since_started_at: datetime | None = None,
    trigger_event_id: str | None = None,
) -> WorkflowRun | None:
    """Re-enrollment + idempotency dedupe query.

    Three modes:

      * ``trigger_event_id`` non-None: exact lookup on
        ``(workflow_id, trigger_event_id)``. Replays of the same
        event hit this branch and refuse the duplicate enrolment
        regardless of re-enrollment rule.
      * ``since_started_at`` set: re-enrollment ``daily`` mode —
        find any run for ``(workflow_id, contact_id)`` started on
        or after the supplied boundary.
      * Neither: re-enrollment ``once`` mode — any prior run for
        ``(workflow_id, contact_id)`` that isn't ``canceled``.

    ``canceled`` runs never block re-enrollment per the Step-5
    spec ("future-version-publishes-re-enrollment-eligible-contacts
    pattern").
    """
    stmt = select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)

    if trigger_event_id is not None:
        stmt = stmt.where(WorkflowRun.trigger_event_id == trigger_event_id)
    else:
        if contact_id is None:
            # Without a contact_id and without a trigger_event_id
            # there's no dedupe key — treat as "no prior run".
            stmt = stmt.where(WorkflowRun.contact_id.is_(None))
        else:
            stmt = stmt.where(WorkflowRun.contact_id == contact_id)
        # Canceled runs do not block re-enrollment.
        stmt = stmt.where(
            WorkflowRun.status != WorkflowRunStatus.canceled
        )
        if since_started_at is not None:
            stmt = stmt.where(WorkflowRun.started_at >= since_started_at)

    stmt = stmt.order_by(WorkflowRun.started_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def next_step_index(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
) -> int:
    """Allocate the next monotonic ``step_index`` for a run. The
    unique ``(run_id, step_index)`` constraint enforces strict
    ordering; collisions surface as IntegrityError + the engine's
    catch-all marks the run errored."""
    result = await session.execute(
        select(func.coalesce(func.max(WorkflowStepRun.step_index), -1))
        .where(WorkflowStepRun.run_id == run_id)
    )
    return int(result.scalar_one()) + 1


__all__ = [
    "add_folder",
    "add_version",
    "add_workflow",
    "count_workflows_in_folder",
    "delete_folder",
    "find_existing_run",
    "get_folder",
    "get_run",
    "get_run_for_processing",
    "get_run_unscoped",
    "get_workflow",
    "get_workflow_by_name",
    "insert_run",
    "insert_step_run",
    "list_active_workflows_for_event",
    "list_folders",
    "list_runs",
    "list_runs_due_for_resume",
    "list_step_runs",
    "list_versions",
    "list_workflows",
    "next_step_index",
]
