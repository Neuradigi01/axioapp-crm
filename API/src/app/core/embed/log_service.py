"""Service layer for `embed_submissions` — the Step 9 submission log.

Two responsibilities:

  1. **Write** — `record(...)` appends one row per submission attempt.
     Called by `submissions.submit` (on the accepted + each spam-reject
     + the invalid-payload path) and by the router's rate-limit branch.
     Like `audit.log`, never raises: a logging-side failure must not
     break the user-facing flow.
  2. **Read** — `list_rows(...)` / `summary(...)` back the admin
     endpoints. Both run inside the active tenant context (RLS
     authorises the read; ORM tenant filter is the belt-and-braces).

Retention: the daily Celery beat task `purge_old_embed_submissions`
in this module deletes rows older than 30 days.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.embed import data_access as _da
from src.app.core.embed.models import EmbedSubmissionLog, EmbedSubmissionOutcome
from src.app.core.embed.schemas import (
    EmbedSubmissionDayBucket,
    EmbedSubmissionSummary,
)
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


RETENTION_DAYS = 30


def hash_ip(ip: str | None) -> str | None:
    """Same 16-char SHA-256 prefix used everywhere else in the embed
    module."""
    if not ip or ip == "unknown":
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


async def record(
    *,
    org_id: uuid.UUID,
    key_id: uuid.UUID | None,
    outcome: EmbedSubmissionOutcome,
    reason: str | None = None,
    ip: str | None = None,
    referrer: str | None = None,
    landing_url: str | None = None,
    lead_id: uuid.UUID | None = None,
) -> None:
    """Append one row. Never raises — a log-write failure must not
    break the submission flow. Opens its own tenant-scoped session
    so callers don't have to worry about context plumbing.
    """
    ctx_token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            _da.insert_submission_log(
                session,
                EmbedSubmissionLog(
                    org_id=org_id,
                    key_id=key_id,
                    lead_id=lead_id,
                    outcome=outcome,
                    reason=reason,
                    ip_hash=hash_ip(ip),
                    referrer=_truncate(referrer, 2048),
                    landing_url=_truncate(landing_url, 2048),
                ),
            )
            await session.commit()
    except Exception:
        logger.exception(
            "embed.log_service.record failed (org=%s outcome=%s)",
            org_id,
            outcome,
        )
    finally:
        reset_context(ctx_token)


def _truncate(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    return value[:length]


async def list_rows(
    session: AsyncSession,
    *,
    outcome: EmbedSubmissionOutcome | None = None,
    range_from: datetime | None = None,
    range_to: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[EmbedSubmissionLog], int]:
    """Paginated list of rows (newest first)."""
    return await _da.list_submission_logs_query(
        session,
        outcome=outcome,
        range_from=range_from,
        range_to=range_to,
        page=page,
        page_size=page_size,
    )


async def summary(
    session: AsyncSession,
    *,
    range_from: datetime,
    range_to: datetime,
) -> EmbedSubmissionSummary:
    """Drives the counts card + bar chart at the top of the
    submission log tab.

    `by_outcome` totals over the window; `by_day` is per-day stacked
    counts, with one entry per calendar day in `[from, to]` so the
    chart's x-axis is dense (zero-count days included).
    """
    outcome_rows = await _da.submission_outcome_totals(
        session, range_from=range_from, range_to=range_to
    )
    by_outcome: dict[str, int] = {outcome.value: 0 for outcome in EmbedSubmissionOutcome}
    for outcome_value, count in outcome_rows:
        key = (
            outcome_value.value
            if isinstance(outcome_value, EmbedSubmissionOutcome)
            else str(outcome_value)
        )
        by_outcome[key] = int(count)

    day_rows = await _da.submission_daily_outcome_buckets(
        session, range_from=range_from, range_to=range_to
    )

    buckets: dict[date, dict[str, int]] = {}
    for day, outcome_value, count in day_rows:
        d = day.date() if isinstance(day, datetime) else day
        key = (
            outcome_value.value
            if isinstance(outcome_value, EmbedSubmissionOutcome)
            else str(outcome_value)
        )
        buckets.setdefault(d, {o.value: 0 for o in EmbedSubmissionOutcome})[key] = int(count)

    by_day: list[EmbedSubmissionDayBucket] = []
    for d in _days_between(range_from.date(), range_to.date()):
        bucket = buckets.get(d, {o.value: 0 for o in EmbedSubmissionOutcome})
        by_day.append(
            EmbedSubmissionDayBucket(
                day=d.isoformat(),
                accepted=bucket["accepted"],
                rejected_spam=bucket["rejected_spam"],
                rate_limited=bucket["rate_limited"],
                invalid_payload=bucket["invalid_payload"],
            )
        )

    return EmbedSubmissionSummary(
        range_from=range_from,
        range_to=range_to,
        by_outcome=by_outcome,  # type: ignore[arg-type]
        by_day=by_day,
    )


def _days_between(start: date, end: date):
    """Yield every calendar date in `[start, end]` inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


async def purge_old_embed_submissions() -> int:
    """Daily Celery-beat task. Deletes every row older than
    `RETENTION_DAYS` days across ALL orgs. Returns the row count
    purged so the worker logs are useful.

    Runs without any tenant context — the cleanup is intentionally
    cross-tenant. RLS is bypassed only because no `app.org_id` is
    set; the explicit WHERE-clause is the only filter. The Celery
    worker runs trusted code so this is safe.
    """
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    async with async_session() as session:
        deleted = await _da.delete_submission_logs_older_than(session, cutoff)
        await session.commit()
    logger.info(
        "embed.purge_old_embed_submissions removed=%d cutoff=%s",
        deleted,
        cutoff.isoformat(),
    )
    return deleted


__all__ = [
    "RETENTION_DAYS",
    "hash_ip",
    "list_rows",
    "purge_old_embed_submissions",
    "record",
    "summary",
]
