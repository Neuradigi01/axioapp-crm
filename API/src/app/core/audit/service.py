"""Audit-log service: ``log(...)`` writer + paginated reader.

``log`` is best-effort by contract: it opens its own session, commits
in isolation from the parent request transaction, and traps every
exception so an audit-storage failure never propagates into a 5xx for
the user-facing flow. Loud failures go to the module logger (and from
there to whatever sink ``logging`` is configured with).

Default values for ``org_id`` and ``user_id`` come from the active
``RequestContext``; the auth login flow passes them explicitly because
the JWT hasn't been issued yet at that point (so the request context
is still empty).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit import data_access as _da
from src.app.core.audit.models import AuditLog
from src.app.shared.context import get_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


async def log(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Persist one audit row. Never raises.

    ``org_id``/``user_id``/``ip``/``ua`` fall back to ``RequestContext``
    when not passed; callers like ``auth.service.login`` pass them
    explicitly because they fire before the request context is populated.
    """
    ctx = get_context()
    resolved_org_id = org_id if org_id is not None else ctx.org_id
    resolved_user_id = user_id if user_id is not None else ctx.user_id

    if resolved_org_id is None:
        # No tenant ⇒ nothing to attach this row to. Skip rather than
        # invent a synthetic org row.
        return

    try:
        async with async_session() as session:
            await _da.insert_audit_log(
                session,
                org_id=resolved_org_id,
                user_id=resolved_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before=before,
                after=after,
                ip=ip,
                ua=ua,
            )
            await session.commit()
    except Exception:
        logger.exception("audit.log failed (action=%s)", action)


async def list_audit_logs(
    session: AsyncSession,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[AuditLog], int]:
    """Return ``(rows, total)``. Tenant scoping is automatic via the ORM
    filter."""
    return await _da.list_audit_logs_query(
        session,
        action=action,
        entity_type=entity_type,
        from_dt=from_dt,
        to_dt=to_dt,
        page=page,
        size=size,
    )
