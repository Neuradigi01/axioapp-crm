"""Audit-log HTTP route.

  GET /api/v1/audit-logs?action=&entity_type=&from=&to=&page=&size=

Gated by the `audit.read` permission. The auto-tenant ORM filter
restricts every query to the caller's org, so a viewer can never see
audit rows belonging to another tenant.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit.schemas import AuditLogOut, AuditLogPage
from src.app.core.audit.service import list_audit_logs
from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    from_dt: datetime | None = Query(None, alias="from"),
    to_dt: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("audit.read")),
) -> AuditLogPage:
    items, total = await list_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        from_dt=from_dt,
        to_dt=to_dt,
        page=page,
        size=size,
    )
    return AuditLogPage(
        items=[AuditLogOut.model_validate(row) for row in items],
        total=total,
        page=page,
        size=size,
    )
