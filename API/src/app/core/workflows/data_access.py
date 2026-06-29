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

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.models import (
    Workflow,
    WorkflowFolder,
    WorkflowStatus,
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


__all__ = [
    "add_folder",
    "add_version",
    "add_workflow",
    "count_workflows_in_folder",
    "delete_folder",
    "get_folder",
    "get_workflow",
    "get_workflow_by_name",
    "list_folders",
    "list_versions",
    "list_workflows",
]
