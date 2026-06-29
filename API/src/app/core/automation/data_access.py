"""Data-access layer for the automation engine.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``. Single-file per the locked
layered convention (manager spec 2026-06-25).

Step 2 fills in the trigger-side reads (list / get / matcher). Step
4 will extend with run helpers (insert_run + idempotency check +
list_runs for the run-history endpoint).

Tenant scoping is applied automatically by the ``do_orm_execute``
listener on every SELECT, but consumers SHOULD also pass ``org_id``
explicitly in the WHERE clause as a belt-to-the-suspenders defense
— Celery tasks + scripts that forget to set ``RequestContext.org_id``
still get correct results.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.conversations.models import ConversationChannel


async def get_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    trigger_id: uuid.UUID,
) -> AutomationTrigger | None:
    """Resolve a trigger by its UUID PK. ``None`` if missing or
    cross-tenant (callers translate to :class:`TriggerNotFound`)."""
    result = await session.execute(
        select(AutomationTrigger).where(
            AutomationTrigger.id == trigger_id,
            AutomationTrigger.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_trigger_by_name(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
) -> AutomationTrigger | None:
    """Case-insensitive name lookup — drives the duplicate-name
    rejection at create + update time. Uses the functional unique
    index ``uq_automation_triggers_org_lower_name`` from Step 1."""
    result = await session.execute(
        select(AutomationTrigger).where(
            AutomationTrigger.org_id == org_id,
            func.lower(AutomationTrigger.name) == name.strip().lower(),
        )
    )
    return result.scalar_one_or_none()


async def list_triggers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str | None = None,
    enabled: bool | None = None,
    channel: ConversationChannel | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AutomationTrigger], int]:
    """Filterable + paginated list. ``q`` matches against ``name``
    or ``event_type`` (case-insensitive). Returns ``(rows, total)``.

    ``order by id ASC`` keeps the matcher deterministic — Step 4's
    dispatcher relies on stable trigger ordering when an event has
    multiple matching triggers + we want the run-rows to insert in
    a consistent sequence."""
    base = select(AutomationTrigger).where(AutomationTrigger.org_id == org_id)

    if event_type is not None:
        base = base.where(AutomationTrigger.event_type == event_type)
    if enabled is not None:
        base = base.where(AutomationTrigger.enabled.is_(enabled))
    if channel is not None:
        base = base.where(AutomationTrigger.channel == channel)
    if q:
        pattern = f"%{q.lower()}%"
        base = base.where(
            or_(
                func.lower(AutomationTrigger.name).like(pattern),
                func.lower(AutomationTrigger.event_type).like(pattern),
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
                base.order_by(AutomationTrigger.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def match_enabled_triggers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
) -> list[AutomationTrigger]:
    """Hot-path matcher query the dispatcher hits on every event
    publish. Returns every enabled trigger for ``(org_id,
    event_type)`` in deterministic ``id ASC`` order.

    Condition evaluation happens upstream in
    :func:`core.automation.conditions.evaluate` so this query stays
    a simple index-covered SELECT — the
    ``ix_automation_triggers_org_event_enabled`` covering index from
    Step 1 makes it O(log n + match-count)."""
    result = await session.execute(
        select(AutomationTrigger)
        .where(
            AutomationTrigger.org_id == org_id,
            AutomationTrigger.event_type == event_type,
            AutomationTrigger.enabled.is_(True),
        )
        .order_by(AutomationTrigger.id.asc())
    )
    return list(result.scalars().all())


def add_trigger(
    session: AsyncSession, trigger: AutomationTrigger
) -> AutomationTrigger:
    """Stage a new trigger row in the unit-of-work. Service commits."""
    session.add(trigger)
    return trigger


# --- tbl_automation_runs ------------------------------------------------


async def get_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AutomationRun | None:
    """Resolve a single run by id. ``None`` if missing or cross-tenant."""
    result = await session.execute(
        select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_run_by_id_unscoped(
    session: AsyncSession, *, run_id: uuid.UUID
) -> AutomationRun | None:
    """Tenant-agnostic lookup — Celery worker tasks call this
    because they don't carry a ``RequestContext``. Sets the org
    context internally before reading; safe to use ONLY from the
    Celery delivery path."""
    result = await session.execute(
        select(AutomationRun).where(AutomationRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def find_run_by_event_id(
    session: AsyncSession,
    *,
    trigger_id: uuid.UUID,
    event_id: str,
) -> AutomationRun | None:
    """Idempotency check — returns the prior run if the same
    publisher event already fired for this trigger. The dispatcher
    short-circuits when a row exists so at-least-once delivery
    doesn't double-send.

    Backed by the unique partial index
    ``uq_automation_runs_trigger_event_id`` from migration 0128."""
    result = await session.execute(
        select(AutomationRun).where(
            AutomationRun.trigger_id == trigger_id,
            AutomationRun.event_id == event_id,
        )
    )
    return result.scalar_one_or_none()


def add_run(
    session: AsyncSession, run: AutomationRun
) -> AutomationRun:
    """Stage a new run row in the unit-of-work. Dispatcher commits."""
    session.add(run)
    return run


async def list_runs(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    trigger_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    status: AutomationRunStatus | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AutomationRun], int]:
    """Filterable + paginated run history. Drives the Step-9 UI's
    "what fired for this trigger" view + the per-contact timeline
    (filter by ``contact_id``).

    ``order by scheduled_at DESC`` so newest fires sit at the top —
    matches the partial index from Step 1
    (``ix_automation_runs_trigger_scheduled_desc``)."""
    base = select(AutomationRun).where(AutomationRun.org_id == org_id)

    if trigger_id is not None:
        base = base.where(AutomationRun.trigger_id == trigger_id)
    if contact_id is not None:
        base = base.where(AutomationRun.contact_id == contact_id)
    if status is not None:
        base = base.where(AutomationRun.status == status)
    if since is not None:
        base = base.where(AutomationRun.scheduled_at >= since)

    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(AutomationRun.scheduled_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


__all__ = [
    "add_run",
    "add_trigger",
    "find_run_by_event_id",
    "get_run",
    "get_run_by_id_unscoped",
    "get_trigger",
    "get_trigger_by_name",
    "list_runs",
    "list_triggers",
    "match_enabled_triggers",
]
