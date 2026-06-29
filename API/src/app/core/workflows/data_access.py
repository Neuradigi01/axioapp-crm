"""Data-access layer for the workflows module — single-file
placeholder per the locked layered convention (manager spec
2026-06-25).

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``.

Step 1 ships the file with no query bodies; Steps 2 / 4 / 5 fill
in the workflow CRUD reads, the run scheduler's pending sweep,
and the trigger matcher's event-type lookup respectively.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows.models import Workflow


async def get_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
) -> Workflow | None:
    """Single-row read by PK + org. Returns ``None`` on miss or
    cross-tenant. Step 2's CRUD endpoints call into this.
    """
    result = await session.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


__all__ = ["get_workflow"]
