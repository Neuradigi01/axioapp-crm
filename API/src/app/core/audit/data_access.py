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
    user_id: uuid.UUID | None = None,
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
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if from_dt is not None:
        filters.append(AuditLog.created_at >= from_dt)
    if to_dt is not None:
        filters.append(AuditLog.created_at <= to_dt)

    base = select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count()).select_from(AuditLog).where(*filters)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(base.offset((page - 1) * size).limit(size))).scalars().all()
    return list(rows), total


async def iter_audit_logs_for_export(
    session: AsyncSession,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 50_000,
) -> list[AuditLog]:
    """Bulk read for CSV export. No pagination — returns up to
    ``limit`` matching rows in one shot so the writer can stream them
    into a single file. Ordered newest-first, same as the paginated
    reader, so the export matches what the operator sees in the UI.

    Tenant scoping stays automatic via ``TenantScoped``. The 50k cap
    is a defence-in-depth guard against an operator who leaves the
    date range unbounded on an org with years of history — anything
    above that suggests a compliance-grade export flow (Sprint 3 track,
    not this one)."""
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if from_dt is not None:
        filters.append(AuditLog.created_at >= from_dt)
    if to_dt is not None:
        filters.append(AuditLog.created_at <= to_dt)

    stmt = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


__all__ = ["insert_audit_log", "iter_audit_logs_for_export", "list_audit_logs_query"]
