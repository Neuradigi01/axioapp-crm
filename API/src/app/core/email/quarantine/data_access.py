"""DAL for the quarantine + filter-rules module.

Pure CRUD. Every mutation stages a change and returns the row; commit
belongs to the caller (service). Reads scope by ``org_id`` explicitly
on top of the tenant listener + RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.quarantine.models import (
    STATUS_AUTO_PURGED,
    STATUS_DISCARDED,
    STATUS_HELD,
    STATUS_RELEASED,
    EmailFilterRule,
    EmailQuarantine,
)


# ---------------------------------------------------------------------------
# Filter rules
# ---------------------------------------------------------------------------


def add_filter_rule(
    session: AsyncSession, row: EmailFilterRule
) -> EmailFilterRule:
    session.add(row)
    return row


async def list_filter_rules(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID | None = None,
) -> list[EmailFilterRule]:
    stmt = select(EmailFilterRule).where(EmailFilterRule.org_id == org_id)
    if endpoint_id is not None:
        stmt = stmt.where(EmailFilterRule.endpoint_id == endpoint_id)
    stmt = stmt.order_by(EmailFilterRule.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_effective_rules(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID | None,
) -> list[EmailFilterRule]:
    """Rules the gate must consult for a message on this (org, endpoint):
    org-wide rules PLUS endpoint-scoped rules for the same endpoint.
    """
    stmt = select(EmailFilterRule).where(EmailFilterRule.org_id == org_id)
    if endpoint_id is not None:
        stmt = stmt.where(
            (EmailFilterRule.endpoint_id.is_(None))
            | (EmailFilterRule.endpoint_id == endpoint_id)
        )
    else:
        stmt = stmt.where(EmailFilterRule.endpoint_id.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_filter_rule_by_id(
    session: AsyncSession, *, id: uuid.UUID, org_id: uuid.UUID
) -> EmailFilterRule | None:
    result = await session.execute(
        select(EmailFilterRule).where(
            EmailFilterRule.id == id,
            EmailFilterRule.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def count_rules_for_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.count(EmailFilterRule.id)).where(
            EmailFilterRule.org_id == org_id
        )
    )
    return int(result.scalar_one())


async def find_rule_by_dedupe(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID | None,
    rule_type: str,
    match_kind: str,
    match_value: str,
) -> EmailFilterRule | None:
    """Look up the row that would collide with the dedupe unique
    index. Consumed by the create-service to raise a clean 409 before
    the DB throws IntegrityError."""
    stmt = select(EmailFilterRule).where(
        EmailFilterRule.org_id == org_id,
        EmailFilterRule.rule_type == rule_type,
        EmailFilterRule.match_kind == match_kind,
        EmailFilterRule.match_value == match_value,
    )
    if endpoint_id is None:
        stmt = stmt.where(EmailFilterRule.endpoint_id.is_(None))
    else:
        stmt = stmt.where(EmailFilterRule.endpoint_id == endpoint_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_filter_rule(
    session: AsyncSession, row: EmailFilterRule
) -> None:
    await session.delete(row)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def add_quarantine(
    session: AsyncSession, row: EmailQuarantine
) -> EmailQuarantine:
    session.add(row)
    return row


async def find_quarantine_by_id(
    session: AsyncSession,
    *,
    id: uuid.UUID,
    org_id: uuid.UUID,
) -> EmailQuarantine | None:
    result = await session.execute(
        select(EmailQuarantine).where(
            EmailQuarantine.id == id,
            EmailQuarantine.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def find_quarantine_by_delivery_id(
    session: AsyncSession, *, mailgun_delivery_id: str
) -> EmailQuarantine | None:
    """Global lookup — the delivery_id is unique across orgs. Consumed
    by the gate to avoid double-quarantine on a retry."""
    result = await session.execute(
        select(EmailQuarantine).where(
            EmailQuarantine.mailgun_delivery_id == mailgun_delivery_id
        )
    )
    return result.scalar_one_or_none()


async def list_quarantine_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: str | None = None,
    reason_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[EmailQuarantine], int]:
    """Paginated list + total-count for the frontend table."""
    base = select(EmailQuarantine).where(EmailQuarantine.org_id == org_id)
    if status is not None:
        base = base.where(EmailQuarantine.status == status)
    if reason_code is not None:
        base = base.where(EmailQuarantine.reason_code == reason_code)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    page_stmt = base.order_by(EmailQuarantine.held_at.desc()).limit(limit).offset(
        offset
    )
    rows = list((await session.execute(page_stmt)).scalars().all())
    return rows, total


async def list_held_older_than(
    session: AsyncSession, *, cutoff: datetime
) -> list[EmailQuarantine]:
    """System-actor call from the auto-purge beat. Cross-tenant."""
    from sqlalchemy import text

    result = await session.execute(
        text(
            """
            SELECT id FROM tbl_email_quarantine
             WHERE status = 'held'
               AND held_at <= :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    ids = [row[0] for row in result.all()]
    if not ids:
        return []
    rows = await session.execute(
        select(EmailQuarantine).where(EmailQuarantine.id.in_(ids))
    )
    return list(rows.scalars().all())


async def mark_released(
    session: AsyncSession,
    *,
    id: uuid.UUID,
    resolved_by_user_id: uuid.UUID | None,
    now: datetime,
) -> None:
    await session.execute(
        update(EmailQuarantine)
        .where(EmailQuarantine.id == id, EmailQuarantine.status == STATUS_HELD)
        .values(
            status=STATUS_RELEASED,
            resolved_at=now,
            resolved_by_user_id=resolved_by_user_id,
        )
    )


async def mark_discarded(
    session: AsyncSession,
    *,
    id: uuid.UUID,
    resolved_by_user_id: uuid.UUID | None,
    now: datetime,
) -> None:
    await session.execute(
        update(EmailQuarantine)
        .where(EmailQuarantine.id == id, EmailQuarantine.status == STATUS_HELD)
        .values(
            status=STATUS_DISCARDED,
            resolved_at=now,
            resolved_by_user_id=resolved_by_user_id,
        )
    )


async def mark_auto_purged(
    session: AsyncSession, *, id: uuid.UUID, now: datetime
) -> None:
    await session.execute(
        update(EmailQuarantine)
        .where(EmailQuarantine.id == id, EmailQuarantine.status == STATUS_HELD)
        .values(status=STATUS_AUTO_PURGED, resolved_at=now)
    )


__all__ = [
    "add_filter_rule",
    "add_quarantine",
    "count_rules_for_org",
    "delete_filter_rule",
    "find_effective_rules",
    "find_filter_rule_by_id",
    "find_quarantine_by_delivery_id",
    "find_quarantine_by_id",
    "find_rule_by_dedupe",
    "list_filter_rules",
    "list_held_older_than",
    "list_quarantine_for_org",
    "mark_auto_purged",
    "mark_discarded",
    "mark_released",
]
