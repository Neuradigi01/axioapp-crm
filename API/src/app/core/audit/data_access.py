"""Data-access layer for the audit-log module.

Pure query helpers — no transactions, no commits. Leaf module; never
imports a ``service.py``.

Two operations:

  * ``insert_audit_log`` — attach an ``AuditLog`` row to the supplied
    session. The caller (``audit.service.log``) opens its own session
    and commits in isolation from the parent request, so failures
    never propagate.
  * ``list_audit_logs_query`` — paginated read + COUNT with optional
    ``action`` / ``entity_type`` / date-range filters. Tenant scoping
    is automatic via the ORM filter on ``TenantScoped``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit.models import AuditLog


async def insert_audit_log(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    ip: str | None,
    ua: str | None,
) -> None:
    """Attach one AuditLog row to ``session``. Caller commits."""
    session.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            ip=ip,
            ua=ua,
        )
    )


async def list_audit_logs_query(
    session: AsyncSession,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[AuditLog], int]:
    """Return ``(rows, total)``. Tenant scoping is automatic via the
    ORM filter on ``TenantScoped``."""
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if from_dt is not None:
        filters.append(AuditLog.created_at >= from_dt)
    if to_dt is not None:
        filters.append(AuditLog.created_at <= to_dt)

    base = select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count()).select_from(AuditLog).where(*filters)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), total


__all__ = ["insert_audit_log", "list_audit_logs_query"]
