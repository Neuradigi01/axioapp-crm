"""Round-robin lead assignment.

`pick_assignee(session, org_id, source)` returns the `user_id` of the
next eligible user in the org, or None if no user has the
`leads.own` permission. The returned id goes onto the new lead's
`assigned_to_id` column.

How round-robin stays fair under concurrent writes:

  1. List eligible users in a deterministic order (`legacy_uuid`
     sorted). Capture the snapshot inside the same transaction
     that increments the counter so the picked user is consistent.

  2. Atomically increment `lead_routing_state.next_assignee_index`
     via `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`. The
     `RETURNING` clause gives us the PRE-UPDATE index in a single
     round trip — no read-then-write race.

  3. `index mod user_count` selects the assignee. As long as the
     user list is stable for the duration of one transaction (it is —
     `permissions.role_permissions` is read-mostly), two concurrent
     ingests get distinct indices and therefore distinct (or
     deterministically modulo-overlapping) assignees.

Strategy dispatch:

  - `round_robin` (v1 default) — described above.
  - `sticky_by_source` (placeholder) — future strategy that pins
    Google leads to one rep, Meta to another, etc. v1 skeleton only:
    falls through to round_robin. The Settings UI exposes the choice
    in Step 8.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


_LEADS_OWN_PERMISSION = "leads.own"


async def pick_assignee(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    source: str | None = None,
) -> Optional[uuid.UUID]:
    """Resolve the next round-robin assignee for `org_id`.

    Returns the user's `legacy_uuid` (matching what
    `leads.assigned_to_id` expects), or None if no eligible user
    exists (the lead is then created unassigned — surfaces in the
    "Unassigned" filter on the kanban).

    `source` is accepted for forward compatibility with the
    `sticky_by_source` strategy; v1 ignores it.
    """
    eligible = await _list_eligible_users(session, org_id=org_id)
    if not eligible:
        logger.info(
            "pick_assignee: no users with %s in org %s — lead unassigned",
            _LEADS_OWN_PERMISSION,
            org_id,
        )
        return None

    # Strategy dispatch. v1 always round-robin; future strategies
    # consult org_settings.lead_routing_config.strategy.
    index = await _next_round_robin_index(
        session, org_id=org_id, modulo=len(eligible)
    )
    return eligible[index]


async def _list_eligible_users(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Every user in `org_id` whose active membership's role has
    `leads.own`. Returned as a list of `legacy_uuid`s, sorted
    deterministically so the same call inside the same transaction
    yields the same ordering.

    Raw SQL because the join path (login → membership → role →
    role_permissions → permissions) doesn't have a clean ORM analogue
    in this codebase. Sorted by `legacy_uuid` (the column ad/widget
    paths already write to `assigned_to_id`).
    """
    sql = text(
        """
        SELECT DISTINCT u.legacy_uuid
        FROM tbl_user_login u
        JOIN tbl_organization_members m
          ON m.user_member_id = u.id
         AND m.is_active = true
         AND m.organization_id = :org_id
        JOIN tbl_role_permissions rp ON rp.role_id = m.role_id
        JOIN tbl_permissions p
          ON p.id = rp.permission_id
         AND p.key = :perm
        WHERE u.is_active = true
          AND u.legacy_uuid IS NOT NULL
        ORDER BY u.legacy_uuid
        """
    )
    rows = (
        await session.execute(
            sql,
            {
                "org_id": str(org_id),
                "perm": _LEADS_OWN_PERMISSION,
            },
        )
    ).fetchall()
    return [r[0] for r in rows]


async def _next_round_robin_index(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    modulo: int,
) -> int:
    """Atomically bump `lead_routing_state.next_assignee_index` for
    `org_id` and return the PRE-INCREMENT value, modulo the current
    eligible-user count.

    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` is the
    single-round-trip atomic operation Postgres supports. The
    returned value is the index we picked; the in-table value is the
    next-up. Two concurrent ingests serialize on the row lock and
    receive distinct return values.

    Modulo is applied AFTER the increment so the in-table counter
    keeps growing monotonically — a future analytics surface that
    asks "how many leads has org X ever ingested?" reads
    `next_assignee_index` directly without needing a separate counter.
    """
    sql = text(
        """
        INSERT INTO tbl_lead_routing_state (org_id, next_assignee_index)
        VALUES (:org_id, 1)
        ON CONFLICT (org_id) DO UPDATE
            SET next_assignee_index =
                  tbl_lead_routing_state.next_assignee_index + 1,
                updated_at = now()
        RETURNING next_assignee_index - 1 AS picked_index
        """
    )
    picked = (
        await session.execute(sql, {"org_id": str(org_id)})
    ).scalar()
    if picked is None:
        # ON CONFLICT path always returns; INSERT path returns the
        # default - 1 = 0. Defence in depth.
        picked = 0
    return int(picked) % modulo


__all__ = ["pick_assignee"]
