"""Service layer for the activities timeline.

Three public entry points:

- **``log(...)``** — internal helper for any module to record an event
  on any entity. Best-effort by contract: it opens its own session,
  commits in isolation from the caller's transaction, and traps every
  exception so a timeline failure can never break the parent flow.
  This mirrors ``audit.log`` and gives the same "fire and forget"
  guarantee modules elsewhere already depend on.

- **``record_in_session(...)``** — same row shape as ``log``, but
  attaches the row to the caller's session and commits nothing. Used
  by sibling modules (e.g. appointments) that need the activity row
  to ride the same transaction as their primary write so a parent
  rollback also rolls back the activity.

- **``list_activities(...)``** — paginated read for one entity's
  timeline, latest first. Used by the HTTP router and any future
  in-process consumer.

Tenant scoping is automatic: ``log()`` reads ``org_id`` from the active
``RequestContext`` when callers don't pass one (the auth login path
passes it explicitly because the context isn't populated yet);
``list_activities()`` runs through the ORM, which auto-applies the
tenant filter.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities import data_access as _da
from src.app.core.activities.models import Activity, ActivityType
from src.app.core.appointments.models import Appointment
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead
from src.app.core.tasks.models import Task
from src.app.core.walk_ins.models import WalkIn
from src.app.shared.context import get_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


# Dispatch table for the `last_activity_at` denormalisation hook.
# Each parent entity that wants its `last_activity_at` column kept
# fresh on every activity insert registers itself here.
_LAST_ACTIVITY_TABLES: dict[str, type] = {
    "contact": Contact,
    "lead": Lead,
    "walk_in": WalkIn,
    "appointment": Appointment,
    "task": Task,
}


async def _bump_last_activity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    timestamp: datetime,
) -> None:
    """Resolve the parent table from the dispatch map and bump its
    ``last_activity_at`` via the DAL. Best-effort: a failure here is
    logged and swallowed; the activity row is the authoritative log
    and the column is just a fast-path read.

    Caller is responsible for committing the session. We deliberately
    do NOT commit inside this helper so the bump rides on the same
    transaction as the activity insert when called from ``create_note``,
    and on the dedicated short-lived session opened by ``log()``.
    """
    table = _LAST_ACTIVITY_TABLES.get(entity_type)
    if table is None:
        return
    try:
        await _da.bump_last_activity(
            session,
            table=table,
            entity_id=entity_id,
            timestamp=timestamp,
        )
    except Exception:
        logger.exception(
            "last_activity_at bump failed (entity_type=%s, entity_id=%s)",
            entity_type,
            entity_id,
        )


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

    ``org_id`` / ``user_id`` fall back to ``RequestContext`` when not
    passed, same convention as ``audit.log``. If no org is resolvable,
    the row is dropped silently (we have nothing to attach it to).
    """
    ctx = get_context()
    resolved_org_id = org_id if org_id is not None else ctx.org_id
    resolved_user_id = user_id if user_id is not None else ctx.user_id
    if resolved_org_id is None:
        return

    try:
        async with async_session() as session:
            activity = await _da.insert_activity(
                session,
                org_id=resolved_org_id,
                entity_type=entity_type,
                entity_id=entity_id,
                type=type,
                payload=payload,
                user_id=resolved_user_id,
            )
            await _bump_last_activity(
                session,
                entity_type=entity_type,
                entity_id=entity_id,
                timestamp=activity.created_at,
            )
            await session.commit()
    except Exception:
        logger.exception(
            "activities.log failed (entity_type=%s, type=%s)", entity_type, type
        )


async def record_in_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    type: ActivityType,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
) -> Activity:
    """Add one activity row to the supplied session and bump the
    parent's ``last_activity_at``. Caller commits.

    Use this when the activity must ride the same transaction as the
    primary write (e.g. appointment reschedule / reassign): a rollback
    of the primary also rolls back the activity. ``log()`` is the
    fire-and-forget alternative for cases where the activity is purely
    informational.
    """
    activity = await _da.insert_activity(
        session,
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        type=type,
        payload=payload,
        user_id=user_id,
    )
    await _bump_last_activity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        timestamp=activity.created_at,
    )
    return activity


async def list_activities(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Activity], int]:
    """Return (rows, total) for one entity's timeline, latest first.

    Tenant scoping is automatic via the ORM filter on ``TenantScoped``.
    """
    return await _da.list_activities_for_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        size=size,
    )


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

    Distinct from ``log()`` because the HTTP path needs to return the
    persisted row (id, created_at) to the caller. Runs inside the
    request's ``AsyncSession`` so the row is visible to the same
    transaction's follow-up reads if any.
    """
    activity = await _da.insert_activity(
        session,
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        type=ActivityType.note,
        payload={"text": text},
        user_id=user_id,
    )
    await _bump_last_activity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        timestamp=activity.created_at,
    )
    await session.commit()
    await session.refresh(activity)
    return activity
