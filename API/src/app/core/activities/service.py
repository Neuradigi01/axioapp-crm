"""Service layer for the activities timeline.

Two public entry points:

- **`log(...)`** — internal helper for any module to record an event
  on any entity. Best-effort by contract: it opens its own session,
  commits in isolation from the caller's transaction, and traps every
  exception so a timeline failure can never break the parent flow.
  This mirrors `audit.log` and gives the same "fire and forget"
  guarantee modules elsewhere already depend on.

- **`list_activities(...)`** — paginated read for one entity's
  timeline, latest first. Used by the HTTP router and any future
  in-process consumer.

Tenant scoping is automatic: `log()` reads `org_id` from the active
`RequestContext` when callers don't pass one (the auth login path
passes it explicitly because the context isn't populated yet);
`list_activities()` runs through the ORM, which auto-applies the
tenant filter.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities.models import Activity, ActivityType
from src.app.shared.context import get_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


async def log(
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    type: ActivityType,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
) -> None:
    """Append one activity row. Never raises.

    `org_id` / `user_id` fall back to `RequestContext` when not passed,
    same convention as `audit.log`. If no org is resolvable, the row
    is dropped silently (we have nothing to attach it to).
    """
    ctx = get_context()
    resolved_org_id = org_id if org_id is not None else ctx.org_id
    resolved_user_id = user_id if user_id is not None else ctx.user_id
    if resolved_org_id is None:
        return

    try:
        async with async_session() as session:
            session.add(
                Activity(
                    org_id=resolved_org_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    type=type,
                    payload=payload or {},
                    user_id=resolved_user_id,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "activities.log failed (entity_type=%s, type=%s)", entity_type, type
        )


async def list_activities(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Activity], int]:
    """Return (rows, total) for one entity's timeline, latest first.

    Tenant scoping is automatic via the ORM filter on `TenantScoped`.
    """
    base = (
        select(Activity)
        .where(Activity.entity_type == entity_type)
        .where(Activity.entity_id == entity_id)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(Activity)
        .where(Activity.entity_type == entity_type)
        .where(Activity.entity_id == entity_id)
    )
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


async def create_note(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    text: str,
) -> Activity:
    """Synchronous-within-request note creation used by the HTTP router.

    Distinct from `log()` because the HTTP path needs to return the
    persisted row (id, created_at) to the caller. Runs inside the
    request's `AsyncSession` so the row is visible to the same
    transaction's follow-up reads if any.
    """
    activity = Activity(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        type=ActivityType.note,
        payload={"text": text},
        user_id=user_id,
    )
    session.add(activity)
    await session.commit()
    await session.refresh(activity)
    return activity
