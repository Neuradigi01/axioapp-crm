"""HTTP routes for the reporting module.

  GET /api/v1/reports/workload?active_only=true

Reads gated on `users.read`. Designed as the first entry point — future
phases will add lead-funnel reports, sales-by-rep, etc., under the
same `/reports` prefix.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.reporting.service import compute_workload
from src.app.core.users.models import User
from src.app.core.users.schemas import (
    OpenRecordsCounts,
    WorkloadEntry,
    WorkloadReport,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/workload", response_model=WorkloadReport)
async def workload_endpoint(
    active_only: bool = Query(default=True),
    user: User = Depends(require_permissions("users.read")),
    session: AsyncSession = Depends(get_db),
) -> WorkloadReport:
    """Per-user open-record counts across the org. Drives the
    Settings → Staff Workload tab plus optional list-page widgets."""
    summary = await compute_workload(
        session, org_id=user.org_id, active_only=active_only
    )
    entries = [
        WorkloadEntry(
            user_id=row["user_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_active=row["is_active"],
            counts=OpenRecordsCounts(**row["counts"]),
        )
        for row in summary["users"]
    ]
    return WorkloadReport(users=entries, as_of=summary["as_of"])
