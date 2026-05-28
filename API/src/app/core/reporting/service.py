"""Reporting service — composes per-user workload counts.

The first report is `compute_workload`, which loops over every member
of the org and runs the same per-entity "open" predicates that
`users/offboarding.compute_open_records_counts` uses for the
deactivation modal. Same predicates → same numbers, so the Settings
→ Staff Workload tab and the deactivation modal never disagree.

Naive N+1 implementation (one set of per-entity counts per user). For
an org with O(20) staff and five entities that's 100 short queries —
fine for the dashboard cadence. If the org outgrows that, the right
fix is a single `GROUP BY assigned_to_id` query per entity; not
worth the complexity yet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.core.users.offboarding import compute_open_records_counts


async def compute_workload(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = True,
) -> dict:
    """Per-user open-record counts across the org.

    `active_only=True` (default) skips deactivated members so the
    Workload tab focuses on live capacity. Pass `False` to include
    deactivated users when reviewing a recent offboarding.
    """
    stmt = (
        select(User, UserInfo, OrganizationMember)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .where(OrganizationMember.organization_id == org_id)
    )
    if active_only:
        stmt = stmt.where(OrganizationMember.is_active.is_(True))

    rows = (await session.execute(stmt)).all()

    entries: list[dict] = []
    for user, info, membership in rows:
        if user.legacy_uuid is None:
            # Shouldn't happen post-DR.6.2 backfill; defensively skip.
            continue
        counts = await compute_open_records_counts(
            session, user_uuid=user.legacy_uuid, org_id=org_id
        )
        entries.append(
            {
                "user_id": user.legacy_uuid,
                "first_name": info.first_name or "",
                "last_name": info.last_name or "",
                "is_active": bool(membership.is_active and user.is_active),
                "counts": {
                    "user_id": user.legacy_uuid,
                    "contacts": counts["contacts"],
                    "leads": counts["leads"],
                    "walk_ins": counts["walk_ins"],
                    "appointments": counts["appointments"],
                    "tasks": counts["tasks"],
                    "total": counts["total"],
                },
            }
        )
    return {
        "users": entries,
        "as_of": datetime.now(timezone.utc),
    }


__all__ = ["compute_workload"]
