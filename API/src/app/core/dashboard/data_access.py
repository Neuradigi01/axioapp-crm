"""Dashboard data-access layer — pure SQL, no transactions, no
business logic. First introduced for the follow-ups widget query
(``tasks/dashboard-updates/``).

The follow-ups queries cross three shape boundaries the ORM makes
awkward:

* ``Task.assigned_to_id`` (UUID) → ``tbl_user_login.legacy_uuid`` →
  ``tbl_user_login.id`` (bigint) → ``tbl_user_info.member_id`` for
  the assignee display name. Two-hop via a legacy compatibility
  column.
* Polymorphic linked entity: ``Task.related_entity_type`` /
  ``related_entity_id`` conditionally join into either
  ``tbl_contacts`` directly or ``tbl_leads`` → ``tbl_contacts``.
* Bucket predicates that mix ``due_at::date`` calendar math with
  status filters on the same 4-value enum.

Raw SQL via ``session.execute(text(...))`` is clearest here — every
column mapped explicitly, no ORM hydration overhead per row.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.dashboard.schemas import FollowupBucket, FollowupCounts


# --- Bucket predicates --------------------------------------------------
#
# The five buckets share the same joined shape; the WHERE varies. We
# express each as a text snippet + bind params so the surrounding
# templates stay readable.
#
# ``today`` — everything due today, actionable (open) or already-done,
#            skips cancelled + missed (terminal closures)
# ``pending`` — today, still to do
# ``completed_today`` — done + last touched today (Task has no
#            dedicated completed_at; updated_at bumps on the status
#            transition and is the closest deterministic proxy)
# ``overdue`` — past-due, still open (cancelled + missed are terminal)
# ``missed`` — terminal missed within the past 7 days


def _bucket_predicate(bucket: FollowupBucket) -> str:
    if bucket == "today":
        return (
            "t.due_at::date = :today "
            "AND t.status IN ('open', 'done')"
        )
    if bucket == "pending":
        return "t.due_at::date = :today AND t.status = 'open'"
    if bucket == "completed_today":
        return "t.status = 'done' AND t.updated_at::date = :today"
    if bucket == "overdue":
        return "t.due_at::date < :today AND t.status = 'open'"
    if bucket == "missed":
        # `seven_days_ago` is pre-computed in Python + bound so we
        # avoid Postgres' bind-param interval coercion complaint on
        # ``:today - INTERVAL '7 days'``.
        return (
            "t.status = 'missed' "
            "AND t.updated_at::date >= :seven_days_ago"
        )
    raise ValueError(f"unknown bucket: {bucket}")


# --- Shared FROM + JOIN template ---------------------------------------
#
# Every follow-ups query starts from the same joined shape:
#   * tbl_tasks (t)
#   * tbl_user_login (ul) via legacy_uuid → for assignee display
#   * tbl_user_info (ui) LEFT JOIN → for assignee first/last name
#   * tbl_contacts (c) LEFT JOIN → when the related entity is a contact
#   * tbl_leads (l) LEFT JOIN → when the related entity is a lead
#   * tbl_contacts (lc) LEFT JOIN via lead → lead's contact for label

_JOINS = """
FROM tbl_tasks t
LEFT JOIN tbl_user_login ul ON ul.legacy_uuid = t.assigned_to_id
LEFT JOIN tbl_user_info ui ON ui.member_id = ul.id
LEFT JOIN tbl_contacts c
       ON t.related_entity_type = 'contact'
      AND c.id = t.related_entity_id
LEFT JOIN tbl_leads l
       ON t.related_entity_type = 'lead'
      AND l.id = t.related_entity_id
LEFT JOIN tbl_contacts lc ON lc.id = l.contact_id
"""


def _base_where_and_params(
    *,
    org_id: uuid.UUID,
    today: date,
    assignee_uuid: uuid.UUID | None,
    followup_type: str | None,
    priority: str | None,
    q: str | None,
) -> tuple[list[str], dict[str, Any]]:
    """Build the shared WHERE fragments (excluding the bucket-specific
    predicate) + the bind-param dict."""
    conditions = ["t.org_id = :org_id"]
    params: dict[str, Any] = {
        "org_id": org_id,
        "today": today,
        # Pre-computed so the missed-bucket predicate doesn't need
        # Postgres date-interval arithmetic (asyncpg refuses to coerce
        # a bound date - interval expression to date otherwise).
        "seven_days_ago": today - timedelta(days=7),
    }

    if assignee_uuid is not None:
        conditions.append("t.assigned_to_id = :assignee_uuid")
        params["assignee_uuid"] = assignee_uuid

    if followup_type is not None:
        conditions.append("t.followup_type = :followup_type")
        params["followup_type"] = followup_type

    if priority is not None:
        conditions.append("t.priority = :priority")
        params["priority"] = priority

    if q:
        # ILIKE the task title + the linked contact fields (both direct
        # and via lead). Trigram indexes on tbl_contacts make this fast
        # enough for reasonable org sizes.
        conditions.append(
            "("
            "t.title ILIKE :q_like OR "
            "c.full_name ILIKE :q_like OR "
            "c.phone ILIKE :q_like OR "
            "c.email ILIKE :q_like OR "
            "lc.full_name ILIKE :q_like OR "
            "lc.phone ILIKE :q_like OR "
            "lc.email ILIKE :q_like"
            ")"
        )
        params["q_like"] = f"%{q}%"

    return conditions, params


# --- Counts -------------------------------------------------------------


async def count_followups_by_bucket(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    today: date,
    assignee_uuid: uuid.UUID | None,
    followup_type: str | None = None,
    priority: str | None = None,
    q: str | None = None,
) -> FollowupCounts:
    """Return the 5 KPI counts in one grouped query.

    Every count respects the same shared filters (org, assignee scope,
    optional followup_type / priority / q) so the widget's chip counters
    and the KPI cards agree with the list body 1:1.
    """
    conditions, params = _base_where_and_params(
        org_id=org_id,
        today=today,
        assignee_uuid=assignee_uuid,
        followup_type=followup_type,
        priority=priority,
        q=q,
    )
    where = " AND ".join(conditions)

    sql = text(
        f"""
        SELECT
          COUNT(*) FILTER (
            WHERE t.due_at::date = :today
              AND t.status IN ('open', 'done')
          ) AS today_total,
          COUNT(*) FILTER (
            WHERE t.due_at::date = :today AND t.status = 'open'
          ) AS pending_today,
          COUNT(*) FILTER (
            WHERE t.status = 'done' AND t.updated_at::date = :today
          ) AS completed_today,
          COUNT(*) FILTER (
            WHERE t.due_at::date < :today AND t.status = 'open'
          ) AS overdue,
          COUNT(*) FILTER (
            WHERE t.status = 'missed'
              AND t.updated_at::date >= :seven_days_ago
          ) AS missed_last_7d
        {_JOINS}
        WHERE {where}
        """
    )
    row = (await session.execute(sql, params)).one()
    return FollowupCounts(
        today_total=int(row.today_total or 0),
        pending_today=int(row.pending_today or 0),
        completed_today=int(row.completed_today or 0),
        overdue=int(row.overdue or 0),
        missed_last_7d=int(row.missed_last_7d or 0),
    )


# --- List ---------------------------------------------------------------


_ORDER_BY_PER_BUCKET: dict[FollowupBucket, str] = {
    # Earlier due-time first, then higher priority. Nulls-last so
    # tasks without a due_at (rare) don't jump to the top.
    "today": (
        "t.due_at ASC NULLS LAST, "
        "CASE t.priority "
        "  WHEN 'high' THEN 0 "
        "  WHEN 'med' THEN 1 "
        "  ELSE 2 "
        "END ASC"
    ),
    "pending": (
        "t.due_at ASC NULLS LAST, "
        "CASE t.priority "
        "  WHEN 'high' THEN 0 "
        "  WHEN 'med' THEN 1 "
        "  ELSE 2 "
        "END ASC"
    ),
    # Most-recently-completed first — the rep wants to see what they
    # just finished at the top.
    "completed_today": "t.updated_at DESC",
    # Oldest overdue first — most urgent to clear.
    "overdue": "t.due_at ASC NULLS LAST",
    # Most-recently-missed first.
    "missed": "t.updated_at DESC",
}


async def list_tasks_for_bucket(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    bucket: FollowupBucket,
    today: date,
    assignee_uuid: uuid.UUID | None,
    followup_type: str | None = None,
    priority: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(rows, total)`` for the given bucket + filters.

    ``rows`` is a list of dicts (one per matching Task) with every
    field the widget needs pre-joined: assignee display name, linked
    entity type + label, notes preview. ``total`` is the un-paginated
    COUNT for the same filter set."""
    conditions, params = _base_where_and_params(
        org_id=org_id,
        today=today,
        assignee_uuid=assignee_uuid,
        followup_type=followup_type,
        priority=priority,
        q=q,
    )
    conditions.append(_bucket_predicate(bucket))
    where = " AND ".join(conditions)

    order_by = _ORDER_BY_PER_BUCKET[bucket]

    # 1. total for pagination
    total_sql = text(f"SELECT COUNT(*) {_JOINS} WHERE {where}")
    total = int((await session.execute(total_sql, params)).scalar_one() or 0)
    if total == 0:
        return [], 0

    # 2. page slice with denormalised assignee + linked entity
    list_sql = text(
        f"""
        SELECT
          t.id AS id,
          t.title AS title,
          t.due_at AS due_at,
          t.priority AS priority,
          t.status AS status,
          t.followup_type AS followup_type,
          LEFT(t.description, 100) AS notes_preview,
          t.assigned_to_id AS assigned_to_id,
          COALESCE(
            TRIM(BOTH ' ' FROM COALESCE(ui.first_name, '') || ' ' || COALESCE(ui.last_name, '')),
            'Unknown'
          ) AS assignee_name,
          t.related_entity_type AS entity_type,
          t.related_entity_id AS entity_id,
          COALESCE(c.full_name, lc.full_name) AS entity_label
        {_JOINS}
        WHERE {where}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
        """
    )
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = (await session.execute(list_sql, params)).mappings().all()
    return [dict(r) for r in rows], total
