"""Per-org usage counters for capped resources.

Backs the `current_provider` callable that Step 4's `@enforces_cap`
decorator hands to the entitlement service: instead of re-counting
the underlying table on every write (an O(N) lock-acquiring hit on
busy resources), we read a single denormalised row.

Public surface:

  - `increment(session, org_id, resource, delta=1)` — atomic bump via
    Postgres `INSERT ... ON CONFLICT DO UPDATE`. Returns the new value.
  - `get(session, org_id, resource)` — current-period value or 0.
  - `snapshot(session, org_id, resources)` — batched read for the
    billing settings page (Step 7's subscription read API uses this).
  - `reset_monthly_counters(session, org_id, next_period_start,
        next_period_end)` — inserts fresh zeroed rows for each monthly
    resource. Called from the rollover Celery task in `tasks.py`.

Period resolution is keyed by the canonical resource taxonomy in
`RESOURCE_PERIOD_KIND` below. Unknown resources raise `KeyError` —
the taxonomy is the source of truth for what is meterable, mirroring
the cap names in `plans.yaml`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.models import UsageCounter
from src.app.core.subscriptions.service import get_active_subscription


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

# Mirror of the cap keys in `plans.yaml`. Keys here are the *meterable*
# resources — anything that should be counted as it accumulates. Caps
# that are pure feature gates (`pipelines`, `form_widgets`,
# `custom_fields_per_entity`) are NOT in this table; they are read
# from the live row count on the underlying table because they change
# infrequently and the read is cheap.
RESOURCE_PERIOD_KIND: dict[str, str] = {
    "contacts": "lifetime",
    "storage_mb": "lifetime",
    "leads_per_month": "monthly",
    "form_submissions_per_month": "monthly",
    "automation_runs_per_month": "monthly",
    "email_sends_per_month": "monthly",
    "sms_sends_per_month": "monthly",
    "api_calls_per_day": "daily",
}


# Used as `period_end` for `lifetime` rows. Postgres `timestamptz`
# accepts year 9999 — used as a recognisable "never expires" sentinel.
_LIFETIME_SENTINEL_END = datetime(9999, 12, 31, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def _utc_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Midnight-to-midnight UTC window covering `now`."""
    moment = now or datetime.now(tz=timezone.utc)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def _resolve_current_period(
    session: AsyncSession, org_id: uuid.UUID, resource: str
) -> tuple[str, datetime, datetime]:
    """Return `(period_kind, period_start, period_end)` for the org's
    current accumulation window for `resource`.

    Raises `KeyError` if the resource is not meterable, or `RuntimeError`
    if the org has no active subscription (and the resource is monthly
    / lifetime — daily resources don't need a subscription).
    """
    try:
        kind = RESOURCE_PERIOD_KIND[resource]
    except KeyError as exc:
        raise KeyError(f"unknown meterable resource: {resource!r}") from exc

    if kind == "daily":
        start, end = _utc_day_bounds()
        return kind, start, end

    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise RuntimeError(
            f"cannot resolve usage period for org {org_id}: no active subscription"
        )

    if kind == "lifetime":
        return kind, sub.created_at, _LIFETIME_SENTINEL_END
    if kind == "monthly":
        return kind, sub.current_period_start, sub.current_period_end
    # Defensive: the taxonomy is the source of truth, but a stray value
    # would silently miscount, so raise rather than guess.
    raise ValueError(f"unsupported period_kind {kind!r} for resource {resource!r}")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def get(
    session: AsyncSession, org_id: uuid.UUID, resource: str
) -> int:
    """Read the current-period counter. Returns 0 if no row exists yet.

    Filters by `period_start` so a stale row from a previous billing
    cycle does not leak into the current window — the rollover task
    inserts the new period's row at boundary, but the previous row
    is left in place as history.
    """
    kind, period_start, _ = await _resolve_current_period(session, org_id, resource)
    row = (
        await session.execute(
            select(UsageCounter.value).where(
                UsageCounter.org_id == org_id,
                UsageCounter.resource == resource,
                UsageCounter.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    return int(row or 0)


async def snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    resources: list[str] | None = None,
) -> dict[str, int]:
    """Read multiple counters in one round-trip.

    Used by the in-app billing page (Step 16) and the subscription
    read API (Step 7) to fill the per-resource progress bars.
    Resources not yet incremented for the current period are reported
    as 0, not omitted — the caller always gets a dict keyed by the
    resources it asked for.
    """
    targets = resources or list(RESOURCE_PERIOD_KIND.keys())
    return {r: await get(session, org_id, r) for r in targets}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

_UPSERT_SQL = text(
    """
    INSERT INTO usage_counters (
        org_id, resource, period_kind, period_start, period_end, value, updated_at
    )
    VALUES (:org_id, :resource, :period_kind, :period_start, :period_end, :delta, now())
    ON CONFLICT (org_id, resource, period_start)
    DO UPDATE SET value = usage_counters.value + EXCLUDED.value, updated_at = now()
    RETURNING value
    """
)


async def increment(
    session: AsyncSession,
    org_id: uuid.UUID,
    resource: str,
    delta: int = 1,
) -> int:
    """Atomically bump the current-period counter and return the new value.

    Race-safe: the underlying `INSERT ... ON CONFLICT DO UPDATE`
    serialises concurrent bumps via the `(org_id, resource,
    period_start)` unique index. Negative `delta` is allowed for
    decrement (e.g., a contact is deleted) but is bounded at >= 0 by
    the caller; this function does not floor the value because going
    transiently negative is informative when reconciling drift.

    Does NOT commit — the caller's session manages the transaction.
    """
    kind, period_start, period_end = await _resolve_current_period(
        session, org_id, resource
    )
    result = await session.execute(
        _UPSERT_SQL,
        {
            "org_id": org_id,
            "resource": resource,
            "period_kind": kind,
            "period_start": period_start,
            "period_end": period_end,
            "delta": delta,
        },
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Period rollover
# ---------------------------------------------------------------------------

async def reset_monthly_counters(
    session: AsyncSession,
    org_id: uuid.UUID,
    next_period_start: datetime,
    next_period_end: datetime,
) -> int:
    """Insert fresh zeroed rows for every `monthly` resource in the new period.

    Returns the count of rows inserted. Idempotent: if rows for
    `(org_id, resource, next_period_start)` already exist, the ON
    CONFLICT clause leaves them untouched.

    `lifetime` and `daily` resources are NOT reset here:
      - lifetime rows carry the sub's `created_at` as `period_start`
        and never roll over.
      - daily rows are reset by `reset_daily_counters` (a separate
        Celery task that runs at midnight UTC).
    """
    inserted = 0
    for resource, kind in RESOURCE_PERIOD_KIND.items():
        if kind != "monthly":
            continue
        result = await session.execute(
            text(
                """
                INSERT INTO usage_counters (
                    org_id, resource, period_kind, period_start, period_end, value, updated_at
                )
                VALUES (:org_id, :resource, 'monthly', :period_start, :period_end, 0, now())
                ON CONFLICT (org_id, resource, period_start) DO NOTHING
                """
            ),
            {
                "org_id": org_id,
                "resource": resource,
                "period_start": next_period_start,
                "period_end": next_period_end,
            },
        )
        inserted += result.rowcount or 0
    return inserted


async def reset_daily_counter_rows(
    session: AsyncSession,
    org_id: uuid.UUID,
    next_day_start: datetime,
    next_day_end: datetime,
) -> int:
    """Insert fresh zeroed rows for every `daily` resource for the next UTC day.

    Same idempotency contract as `reset_monthly_counters`.
    """
    inserted = 0
    for resource, kind in RESOURCE_PERIOD_KIND.items():
        if kind != "daily":
            continue
        result = await session.execute(
            text(
                """
                INSERT INTO usage_counters (
                    org_id, resource, period_kind, period_start, period_end, value, updated_at
                )
                VALUES (:org_id, :resource, 'daily', :period_start, :period_end, 0, now())
                ON CONFLICT (org_id, resource, period_start) DO NOTHING
                """
            ),
            {
                "org_id": org_id,
                "resource": resource,
                "period_start": next_day_start,
                "period_end": next_day_end,
            },
        )
        inserted += result.rowcount or 0
    return inserted
