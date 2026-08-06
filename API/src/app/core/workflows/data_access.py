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

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.models import (
    Workflow,
    WorkflowEventWait,
    WorkflowFolder,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowSchedule,
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


async def list_workflow_names(session: AsyncSession, *, org_id: uuid.UUID) -> list[str]:
    """Every workflow name in the org. Powers the gallery-clone path's
    name-uniqification — avoids an N+1 retry loop on collision."""
    result = await session.execute(select(Workflow.name).where(Workflow.org_id == org_id))
    return [row for (row,) in result.all()]


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

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(Workflow.updated_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


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
    """List page (``tasks/workflow-scheduling`` Step 5) variant of
    :func:`list_workflows`. Joins a per-workflow aggregate over
    ``tbl_workflow_schedules`` so each row carries
    ``(active_schedule_count, min_next_run_at)`` in ONE query — no
    N+1. ``has_schedule=True`` narrows to workflows with ≥1 active
    schedule.

    Returns ``(rows, total)`` where each row is a 3-tuple. Original
    :func:`list_workflows` (2-tuple return) stays untouched so
    non-list-page callers don't have to change."""
    # Correlated aggregate — one row per workflow, NULL when the
    # workflow has no active schedule. LATERAL not required — a
    # scalar subquery per column keeps the query planner happy and
    # returns the same shape with lower join cost.
    count_expr = (
        select(func.count(WorkflowSchedule.id))
        .where(
            WorkflowSchedule.workflow_id == Workflow.id,
            WorkflowSchedule.active == True,  # noqa: E712
        )
        .correlate(Workflow)
        .scalar_subquery()
    )
    min_next_run_expr = (
        select(func.min(WorkflowSchedule.next_run_at))
        .where(
            WorkflowSchedule.workflow_id == Workflow.id,
            WorkflowSchedule.active == True,  # noqa: E712
        )
        .correlate(Workflow)
        .scalar_subquery()
    )

    base = select(
        Workflow,
        count_expr.label("active_schedule_count"),
        min_next_run_expr.label("min_next_run_at"),
    ).where(Workflow.org_id == org_id)

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
    if has_schedule is True:
        base = base.where(count_expr > 0)
    elif has_schedule is False:
        base = base.where(count_expr == 0)

    # Count subquery — same predicate set, but strip the aggregate
    # columns so the count is one row per workflow.
    count_base = select(Workflow.id).where(Workflow.org_id == org_id)
    if status is not None:
        count_base = count_base.where(Workflow.status == status)
    if category is not None:
        count_base = count_base.where(Workflow.category == category)
    if folder_id is not None:
        count_base = count_base.where(Workflow.folder_id == folder_id)
    if q is not None and q.strip():
        like = f"%{q.strip().lower()}%"
        count_base = count_base.where(
            or_(
                func.lower(Workflow.name).like(like),
                func.lower(func.coalesce(Workflow.description, "")).like(like),
            )
        )
    if has_schedule is True:
        count_base = count_base.where(count_expr > 0)
    elif has_schedule is False:
        count_base = count_base.where(count_expr == 0)
    total = (
        await session.execute(select(func.count()).select_from(count_base.subquery()))
    ).scalar_one()

    result = await session.execute(
        base.order_by(Workflow.updated_at.desc()).offset(offset).limit(limit)
    )
    rows: list[tuple[Workflow, int, datetime | None]] = [
        (wf, int(cnt or 0), nxt) for wf, cnt, nxt in result.all()
    ]
    return rows, int(total)


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
    limit: int | None = None,
    offset: int = 0,
) -> list[WorkflowVersion]:
    """Append-only version history, newest first. Step 17's UI
    surfaces this for diff/revert. Optional ``limit`` / ``offset``
    pagination is honoured when supplied — defaults to "all rows"."""
    stmt = (
        select(WorkflowVersion)
        .where(
            WorkflowVersion.org_id == org_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .order_by(WorkflowVersion.version.desc())
    )
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_versions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> int:
    """Total version rows for one workflow — feeds the drawer's
    paginator `total`."""
    result = await session.execute(
        select(func.count())
        .select_from(WorkflowVersion)
        .where(
            WorkflowVersion.org_id == org_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
    )
    return int(result.scalar_one() or 0)


async def get_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version: int,
) -> WorkflowVersion | None:
    """Resolve one specific historical version. ``None`` when missing.

    Used by the rollback service to fetch the graph to restore, and
    by the read endpoint that powers the version-history drawer's
    preview overlay."""
    result = await session.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.org_id == org_id,
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


# --- stage-only writes (caller commits) --------------------------------


def add_workflow(session: AsyncSession, workflow: Workflow) -> Workflow:
    """Register a new Workflow for INSERT. Caller commits."""
    session.add(workflow)
    return workflow


def add_version(session: AsyncSession, version: WorkflowVersion) -> WorkflowVersion:
    """Register a new WorkflowVersion for INSERT. Caller commits."""
    session.add(version)
    return version


def add_folder(session: AsyncSession, folder: WorkflowFolder) -> WorkflowFolder:
    """Register a new WorkflowFolder for INSERT. Caller commits."""
    session.add(folder)
    return folder


async def delete_folder(session: AsyncSession, folder: WorkflowFolder) -> None:
    """Hard delete on a folder row. Caller commits. Service checks
    ``count_workflows_in_folder`` first + raises 409 when non-empty."""
    await session.delete(folder)


# --- run helpers (Step 4) ----------------------------------------------


def insert_run(session: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    """Stage a new WorkflowRun for INSERT. Caller commits."""
    session.add(run)
    return run


def insert_step_run(session: AsyncSession, step_run: WorkflowStepRun) -> WorkflowStepRun:
    """Stage a new WorkflowStepRun for INSERT. Caller commits."""
    session.add(step_run)
    return step_run


async def get_run_unscoped(session: AsyncSession, *, run_id: uuid.UUID) -> WorkflowRun | None:
    """Cross-tenant single-row read by PK. The Celery worker calls
    this BEFORE setting ``RequestContext.org_id`` — once it has
    the run, it reads ``run.org_id`` and sets the context for the
    rest of the dispatch."""
    result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    return result.scalar_one_or_none()


async def get_run_for_processing(session: AsyncSession, *, run_id: uuid.UUID) -> WorkflowRun | None:
    """Locked single-row read used by the Celery step processor.
    Acquires a row-level lock via ``SELECT ... FOR UPDATE SKIP
    LOCKED`` so two concurrent workers can't process the same run
    in parallel — the loser gets ``None`` + bails out cleanly.

    Caller's transaction holds the lock until commit / rollback.
    """
    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update(skip_locked=True)
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

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(WorkflowRun.started_at.desc()).offset(offset).limit(limit)
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
        stmt = stmt.where(WorkflowRun.status != WorkflowRunStatus.canceled)
        if since_started_at is not None:
            stmt = stmt.where(WorkflowRun.started_at >= since_started_at)

    stmt = stmt.order_by(WorkflowRun.started_at.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def insert_event_wait(session: AsyncSession, wait: WorkflowEventWait) -> WorkflowEventWait:
    """Stage a new event-wait row for INSERT. Caller commits."""
    session.add(wait)
    return wait


async def find_waits_for_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    contact_id: uuid.UUID | None,
    now: datetime | None = None,
) -> list[WorkflowEventWait]:
    """Hot-path resume lookup hit on every published event by the
    trigger handler. Returns every wait row in ``org_id`` matching
    ``event_type`` whose ``expires_at`` is still in the future.

    Contact matching: when the wait row's ``contact_id`` is NULL,
    the wait matches ANY event of the type (org-wide events like
    ``time.daily_tick``). When the wait row's ``contact_id`` is
    set, the published event's ``contact_id`` must equal it.

    Backed by the partial index ``ix_workflow_event_waits_lookup``
    so the per-event check stays cheap even as the table grows.
    """
    from sqlalchemy import or_ as _or

    now = now or datetime.utcnow()
    stmt = (
        select(WorkflowEventWait)
        .where(WorkflowEventWait.org_id == org_id)
        .where(WorkflowEventWait.event_type == event_type)
        .where(WorkflowEventWait.expires_at > now)
    )
    if contact_id is None:
        # Only wildcard-contact waits match.
        stmt = stmt.where(WorkflowEventWait.contact_id.is_(None))
    else:
        # Either explicit match or wildcard wait.
        stmt = stmt.where(
            _or(
                WorkflowEventWait.contact_id == contact_id,
                WorkflowEventWait.contact_id.is_(None),
            )
        )
    return list((await session.execute(stmt)).scalars().all())


async def list_expired_waits(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> list[WorkflowEventWait]:
    """Beat-driven sweep target — waits whose ``expires_at <= now``.
    The sweep resumes each on its node's ``timeout`` outbound edge
    + deletes the row.

    Cross-tenant — caller opens a session WITHOUT setting
    ``RequestContext.org_id`` so the partial-index scan returns
    every org's expired waits in one pass."""
    now = now or datetime.utcnow()
    stmt = (
        select(WorkflowEventWait)
        .where(WorkflowEventWait.expires_at <= now)
        .order_by(WorkflowEventWait.expires_at.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_event_wait(session: AsyncSession, wait: WorkflowEventWait) -> None:
    """Hard-delete a wait row. Caller commits. Used after a
    successful resume so the same wait can't fire twice."""
    await session.delete(wait)


async def list_waits_for_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[WorkflowEventWait]:
    """All parked waits for one run — drives Step 19's run-detail
    drawer ("this run is waiting on event X until Y")."""
    stmt = (
        select(WorkflowEventWait)
        .where(WorkflowEventWait.org_id == org_id)
        .where(WorkflowEventWait.run_id == run_id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_recent_marketing_sends(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    since: datetime,
) -> int:
    """Step 12 — frequency-cap counter. Returns the total number of
    marketing sends to ``contact_id`` since ``since``, across BOTH
    workflow send actions (``tbl_workflow_step_runs`` whose
    ``payload.category='marketing'`` + ``status='completed'``) AND
    campaign blasts (``tbl_campaign_messages`` whose parent campaign
    has the marketing flag + status='sent').

    Both sub-counts are computed with explicit ``org_id`` filters
    even though the ``do_orm_execute`` listener auto-filters
    TenantScoped models — keeps the query correct when the Celery
    worker calls into the compliance check without an active
    RequestContext.
    """
    from sqlalchemy import func as _func

    from src.app.core.campaigns.models import (
        CampaignMessage,
        CampaignMessageStatus,
    )
    from src.app.core.workflows.models import (
        WorkflowStepRun,
        WorkflowStepRunStatus,
    )

    # Workflow side: completed step_runs whose payload tagged the
    # send as marketing-category. The payload column is JSONB so the
    # filter goes through the ``->>`` text accessor.
    workflow_count = (
        await session.execute(
            select(_func.count(WorkflowStepRun.id))
            .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.run_id)
            .where(WorkflowStepRun.org_id == org_id)
            .where(WorkflowRun.contact_id == contact_id)
            .where(WorkflowStepRun.status == WorkflowStepRunStatus.completed)
            .where(WorkflowStepRun.started_at >= since)
            .where(WorkflowStepRun.payload["category"].astext == "marketing")
        )
    ).scalar_one()

    # Campaign side: every CampaignMessage row (status='sent' or
    # 'delivered' / 'read') addressed to this contact since
    # ``since``. Campaigns are categorised at the parent row, but
    # in v1 every campaign is treated as marketing — the
    # compliance check just counts campaign sends regardless of
    # category (matches HubSpot's "campaigns count toward the cap"
    # rule).
    campaign_count = (
        await session.execute(
            select(_func.count(CampaignMessage.id))
            .where(CampaignMessage.org_id == org_id)
            .where(CampaignMessage.contact_id == contact_id)
            .where(
                CampaignMessage.status.in_(
                    (
                        CampaignMessageStatus.sent,
                        CampaignMessageStatus.delivered,
                        CampaignMessageStatus.read,
                    )
                )
            )
            .where(CampaignMessage.sent_at.is_not(None))
            .where(CampaignMessage.sent_at >= since)
        )
    ).scalar_one()

    return int(workflow_count) + int(campaign_count)


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
        select(func.coalesce(func.max(WorkflowStepRun.step_index), -1)).where(
            WorkflowStepRun.run_id == run_id
        )
    )
    return int(result.scalar_one()) + 1


# --- Step 19: analytics + cached counters --------------------------------


async def aggregate_runs_in_window(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> dict[str, int | float | None]:
    """Headline counters for the analytics dashboard. One round-trip
    via FILTER aggregates. Returns ``enrolled / completed /
    goal_reached / errored / running`` counts plus the average
    completion time (seconds) across completed runs."""
    stmt = select(
        func.count(WorkflowRun.id).label("enrolled"),
        func.count(WorkflowRun.id)
        .filter(WorkflowRun.status == WorkflowRunStatus.completed)
        .label("completed"),
        func.count(WorkflowRun.id)
        .filter(WorkflowRun.outcome == "goal_reached")
        .label("goal_reached"),
        func.count(WorkflowRun.id)
        .filter(WorkflowRun.status == WorkflowRunStatus.errored)
        .label("errored"),
        func.count(WorkflowRun.id)
        .filter(WorkflowRun.status == WorkflowRunStatus.running)
        .label("running"),
        func.avg(
            func.extract("epoch", WorkflowRun.completed_at)
            - func.extract("epoch", WorkflowRun.started_at)
        )
        .filter(WorkflowRun.status == WorkflowRunStatus.completed)
        .label("avg_completion_seconds"),
    ).where(
        WorkflowRun.org_id == org_id,
        WorkflowRun.workflow_id == workflow_id,
        WorkflowRun.started_at >= since,
        WorkflowRun.started_at < until,
    )
    row = (await session.execute(stmt)).one()
    return {
        "enrolled": int(row.enrolled or 0),
        "completed": int(row.completed or 0),
        "goal_reached": int(row.goal_reached or 0),
        "errored": int(row.errored or 0),
        "running": int(row.running or 0),
        "avg_completion_seconds": (
            float(row.avg_completion_seconds) if row.avg_completion_seconds is not None else None
        ),
    }


async def aggregate_funnel(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> list[dict[str, str | int]]:
    """Per-node funnel: groups step_runs (joined to their parent
    run for the start-time window) by ``node_id`` + ``status``.
    Returns one dict per ``node_id`` with completed / skipped /
    errored / total counts. The frontend joins this against the
    workflow graph for ordering + node labels."""
    stmt = (
        select(
            WorkflowStepRun.node_id,
            WorkflowStepRun.status,
            func.count(WorkflowStepRun.id).label("count"),
        )
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.run_id)
        .where(
            WorkflowStepRun.org_id == org_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.started_at >= since,
            WorkflowRun.started_at < until,
        )
        .group_by(WorkflowStepRun.node_id, WorkflowStepRun.status)
    )
    rows = (await session.execute(stmt)).all()
    by_node: dict[str, dict[str, int]] = {}
    for node_id, status_value, count in rows:
        status_str = getattr(status_value, "value", status_value)
        bucket = by_node.setdefault(
            node_id,
            {"completed": 0, "skipped": 0, "errored": 0, "running": 0, "pending": 0},
        )
        bucket[str(status_str)] = int(count)
    out: list[dict[str, str | int]] = []
    for node_id, counts in by_node.items():
        total = sum(counts.values())
        out.append(
            {
                "node_id": node_id,
                "total": total,
                "completed_count": counts.get("completed", 0),
                "skipped_count": counts.get("skipped", 0),
                "errored_count": counts.get("errored", 0),
            }
        )
    return out


async def aggregate_skip_reasons(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> dict[str, dict[str, int]]:
    """``{node_id: {skip_reason: count}}`` — the per-step breakdown
    the funnel-click drawer renders. Filters to skipped step_runs
    with a non-null ``skip_reason``."""
    stmt = (
        select(
            WorkflowStepRun.node_id,
            WorkflowStepRun.skip_reason,
            func.count(WorkflowStepRun.id).label("count"),
        )
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.run_id)
        .where(
            WorkflowStepRun.org_id == org_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.started_at >= since,
            WorkflowRun.started_at < until,
            WorkflowStepRun.skip_reason.is_not(None),
        )
        .group_by(WorkflowStepRun.node_id, WorkflowStepRun.skip_reason)
    )
    rows = (await session.execute(stmt)).all()
    out: dict[str, dict[str, int]] = {}
    for node_id, reason, count in rows:
        out.setdefault(node_id, {})[str(reason)] = int(count)
    return out


async def aggregate_daily_rate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> list[dict[str, str | int]]:
    """Daily series for sparklines. One row per day with
    ``enrolled / completed / goal_reached`` counts. The frontend
    fills gaps for days with no runs."""
    day = func.date_trunc("day", WorkflowRun.started_at)
    stmt = (
        select(
            day.label("day"),
            func.count(WorkflowRun.id).label("enrolled"),
            func.count(WorkflowRun.id)
            .filter(WorkflowRun.status == WorkflowRunStatus.completed)
            .label("completed"),
            func.count(WorkflowRun.id)
            .filter(WorkflowRun.outcome == "goal_reached")
            .label("goal_reached"),
        )
        .where(
            WorkflowRun.org_id == org_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.started_at >= since,
            WorkflowRun.started_at < until,
        )
        .group_by(day)
        .order_by(day)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "date": row.day.date().isoformat(),
            "enrolled": int(row.enrolled or 0),
            "completed": int(row.completed or 0),
            "goal_reached": int(row.goal_reached or 0),
        }
        for row in rows
    ]


async def aggregate_send_metrics(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> list[dict[str, str | int]]:
    """Per-channel send rollup. A "send" step_run is identified by
    ``node_id``-derived channel + the node's ``type`` (looked up
    later by the service against the workflow graph). At the DAL
    level we return ``{node_id, status, count}`` grouped tuples;
    the service maps ``node_id → channel`` via the graph."""
    stmt = (
        select(
            WorkflowStepRun.node_id,
            WorkflowStepRun.status,
            func.count(WorkflowStepRun.id).label("count"),
        )
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.run_id)
        .where(
            WorkflowStepRun.org_id == org_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.started_at >= since,
            WorkflowRun.started_at < until,
        )
        .group_by(WorkflowStepRun.node_id, WorkflowStepRun.status)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "node_id": node_id,
            "status": str(getattr(status_value, "value", status_value)),
            "count": int(count),
        }
        for node_id, status_value, count in rows
    ]


async def refresh_cached_counters(
    session: AsyncSession,
    *,
    today_midnight_utc: datetime,
) -> int:
    """Cross-tenant 5-minute beat refresh. Recomputes
    ``cached_running_count`` (live count of running runs) +
    ``cached_completed_today_count`` (completed runs since UTC
    midnight) for every workflow in one UPDATE-FROM-AGGREGATE.

    Cross-tenant intentionally — the beat task opens the session
    without a tenant context. Returns the number of workflow rows
    updated. NO ``session.commit()`` here — the service layer
    commits."""
    from sqlalchemy import update

    running_subq = (
        select(
            WorkflowRun.workflow_id.label("workflow_id"),
            func.count(WorkflowRun.id).label("running_count"),
        )
        .where(WorkflowRun.status == WorkflowRunStatus.running)
        .group_by(WorkflowRun.workflow_id)
        .subquery()
    )
    completed_today_subq = (
        select(
            WorkflowRun.workflow_id.label("workflow_id"),
            func.count(WorkflowRun.id).label("completed_today_count"),
        )
        .where(
            WorkflowRun.status == WorkflowRunStatus.completed,
            WorkflowRun.completed_at >= today_midnight_utc,
        )
        .group_by(WorkflowRun.workflow_id)
        .subquery()
    )

    # Wipe to zero first so workflows with no recent activity drop
    # back to 0 (otherwise they'd carry stale counts forever).
    await session.execute(
        update(Workflow).values(
            cached_running_count=0,
            cached_completed_today_count=0,
        )
    )

    # Per-row UPDATE keyed on workflow_id. Separate statements so
    # the partial coverage (some workflows in one subquery + not the
    # other) doesn't drop rows.
    await session.execute(
        update(Workflow)
        .values(cached_running_count=running_subq.c.running_count)
        .where(Workflow.id == running_subq.c.workflow_id)
    )
    result = await session.execute(
        update(Workflow)
        .values(cached_completed_today_count=completed_today_subq.c.completed_today_count)
        .where(Workflow.id == completed_today_subq.c.workflow_id)
    )
    return int(result.rowcount or 0)


async def get_run_with_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> tuple[WorkflowRun, Workflow] | None:
    """Single round-trip for the Step-19 run-detail page header —
    returns the run + its parent workflow. ``None`` on miss or
    cross-tenant."""
    stmt = (
        select(WorkflowRun, Workflow)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.org_id == org_id,
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return row[0], row[1]


# --- workflow-scheduling — schedule CRUD --------------------------------
#
# `tasks/workflow-scheduling` Step 1. Pure DAL: no transactions, no
# audit, no side-effects. Service layer (Step 2) owns the txn +
# validation + event emission. Sweep (Step 2) uses
# `select_due_schedules_for_update_skip_locked` inside a service-owned
# txn to lock rows for dispatch.


async def insert_schedule(
    session: AsyncSession,
    *,
    schedule: WorkflowSchedule,
) -> WorkflowSchedule:
    """Stage an insert on the session. Caller commits."""
    session.add(schedule)
    return schedule


async def get_schedule_by_id_and_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> WorkflowSchedule | None:
    """Single-row read by PK + org. ``None`` on miss or cross-tenant
    — service layer maps to 404 (never 403; no info leak)."""
    result = await session.execute(
        select(WorkflowSchedule).where(
            WorkflowSchedule.id == schedule_id,
            WorkflowSchedule.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_schedules_for_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> list[WorkflowSchedule]:
    """All schedules attached to a workflow — Builder attach panel
    (Step 4) reads via this. Ordered by ``created_at ASC`` so the
    operator's first-added shows first."""
    result = await session.execute(
        select(WorkflowSchedule)
        .where(
            WorkflowSchedule.org_id == org_id,
            WorkflowSchedule.workflow_id == workflow_id,
        )
        .order_by(WorkflowSchedule.created_at.asc())
    )
    return list(result.scalars().all())


async def list_active_schedules_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[WorkflowSchedule]:
    """Every active schedule for an org — powers the per-org cap
    enforcement + the "you have 4 active schedules" org-summary hint."""
    result = await session.execute(
        select(WorkflowSchedule).where(
            WorkflowSchedule.org_id == org_id,
            WorkflowSchedule.active == True,  # noqa: E712 — SQLAlchemy filter
        )
    )
    return list(result.scalars().all())


async def count_active_schedules_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> int:
    """Cheap counter for the 500-schedule cap check. Service layer
    wraps the ``SELECT COUNT + INSERT`` in a row-lock on the org
    row (via ``FOR UPDATE``) so the cap can't be raced past 500."""
    result = await session.execute(
        select(func.count(WorkflowSchedule.id)).where(
            WorkflowSchedule.org_id == org_id,
            WorkflowSchedule.active == True,  # noqa: E712
        )
    )
    return int(result.scalar_one())


async def update_schedule_fields(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
    fields: dict,
) -> int:
    """Partial UPDATE of a schedule row by PK + org. Returns the
    row-count Postgres reports (1 on hit, 0 on cross-tenant / not
    found). ``updated_at`` is server-set here so the ETag advances
    on every write; service layer must not pass ``updated_at`` in
    ``fields`` (kept out via the ``ScheduleUpdate`` schema)."""
    if not fields:
        return 0
    stmt = (
        update(WorkflowSchedule)
        .where(
            WorkflowSchedule.id == schedule_id,
            WorkflowSchedule.org_id == org_id,
        )
        .values(**fields, updated_at=func.now())
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def delete_schedule(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> int:
    """Hard delete by PK + org. Returns rowcount (1 on hit, 0
    otherwise)."""
    result = await session.execute(
        delete(WorkflowSchedule).where(
            WorkflowSchedule.id == schedule_id,
            WorkflowSchedule.org_id == org_id,
        )
    )
    return result.rowcount or 0


async def select_due_schedules_for_update_skip_locked(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> list[WorkflowSchedule]:
    """Sweep hot path. Picks up to ``limit`` schedules whose
    ``next_run_at <= now`` and ``active = true``, joined against
    ``tbl_workflows.status = 'active'``. ``FOR UPDATE SKIP LOCKED``
    guarantees at most one worker dispatches each row per tick.

    This is a **cross-org scan** — the sweep worker runs as a
    service role (no request context / RLS org GUC). The service
    layer's dispatch loop MUST set ``SET LOCAL app.current_org_id
    = <schedule.org_id>`` before calling ``engine.start_run`` for
    per-row tenancy. Explicit ``org_id`` FK join on ``tbl_workflows``
    is belt-and-braces (RLS bypass or context leak still lands each
    fire in the right org).

    Ordering by ``next_run_at`` so the most-overdue rows fire first
    — mitigates thrash under backlog."""
    stmt = (
        select(WorkflowSchedule)
        .join(Workflow, Workflow.id == WorkflowSchedule.workflow_id)
        .where(
            WorkflowSchedule.active == True,  # noqa: E712
            WorkflowSchedule.next_run_at != None,  # noqa: E711
            WorkflowSchedule.next_run_at <= now,
            Workflow.status == WorkflowStatus.active,
            Workflow.org_id == WorkflowSchedule.org_id,  # belt-and-braces
        )
        .order_by(WorkflowSchedule.next_run_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True, of=WorkflowSchedule)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def set_current_org_context(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> None:
    """Set the ``app.current_org_id`` GUC on the current transaction
    so RLS policies see the tenant. Used by the schedule sweep before
    each per-schedule dispatch so ``engine.start_run`` writes land under
    the schedule's org even though the sweep worker itself runs as a
    service role with no request context.

    NOOP outside a transaction — Postgres requires ``SET LOCAL`` to
    live inside a transaction, so callers must be inside one. Caller
    is the service-layer dispatch loop (per-row savepoint)."""
    await session.execute(
        sql_text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )


async def count_recent_workflow_runs_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    since: datetime,
) -> int:
    """How many workflow runs were started for this org since
    ``since``? Powers the schedule sweep's per-org fires-per-hour
    rate-limit check (README locked decision:
    ``max_fires_per_hour_per_org = 1000``)."""
    result = await session.execute(
        select(func.count(WorkflowRun.id)).where(
            WorkflowRun.org_id == org_id,
            WorkflowRun.started_at >= since,
        )
    )
    return int(result.scalar_one())


async def select_orphaned_pending_runs(
    session: AsyncSession,
    *,
    older_than: datetime,
    limit: int = 100,
) -> list[WorkflowRun]:
    """Orphan-run reaper (Step 6). Picks up ``pending`` runs whose
    ``started_at < older_than`` — typically ``now - 1 hour``. These
    are the runs left behind when a Celery worker died between
    ``engine.start_run`` commit and the first hop's dispatch. The
    reaper marks them ``errored`` with a distinctive
    ``error_reason='orphaned_pending'``.

    Also cross-org — same tenancy discipline as
    :func:`select_due_schedules_for_update_skip_locked`."""
    stmt = (
        select(WorkflowRun)
        .where(
            WorkflowRun.status == WorkflowRunStatus.pending,
            WorkflowRun.started_at < older_than,
        )
        .order_by(WorkflowRun.started_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "add_folder",
    "add_version",
    "add_workflow",
    "aggregate_daily_rate",
    "aggregate_funnel",
    "aggregate_runs_in_window",
    "aggregate_send_metrics",
    "aggregate_skip_reasons",
    "count_active_schedules_for_org",
    "count_recent_marketing_sends",
    "count_recent_workflow_runs_for_org",
    "count_versions",
    "count_workflows_in_folder",
    "delete_event_wait",
    "delete_folder",
    "delete_schedule",
    "find_existing_run",
    "find_waits_for_event",
    "get_folder",
    "get_run",
    "get_run_for_processing",
    "get_run_unscoped",
    "get_run_with_workflow",
    "get_schedule_by_id_and_org",
    "get_version",
    "get_workflow",
    "get_workflow_by_name",
    "insert_event_wait",
    "insert_run",
    "insert_schedule",
    "insert_step_run",
    "list_active_schedules_for_org",
    "list_active_workflows_for_event",
    "list_expired_waits",
    "list_folders",
    "list_runs",
    "list_runs_due_for_resume",
    "list_schedules_for_workflow",
    "list_step_runs",
    "list_versions",
    "list_waits_for_run",
    "list_workflows",
    "list_workflows_with_schedule_summary",
    "next_step_index",
    "refresh_cached_counters",
    "select_due_schedules_for_update_skip_locked",
    "select_orphaned_pending_runs",
    "set_current_org_context",
    "update_schedule_fields",
]
