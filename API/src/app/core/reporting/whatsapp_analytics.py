"""WhatsApp conversation analytics
(whatsapp-platform-upgrade Step 20).

Four read-only aggregation queries that drive the
``/user/reports/whatsapp`` manager dashboard:

  * ``volume`` — sent / received / failed counts bucketed by date.
  * ``response_time`` — median + p95 of first-staff-reply latency,
    optionally grouped by agent.
  * ``outcomes`` — conversation status distribution + tag breakdown.
  * ``agent_leaderboard`` — per-agent response time + resolution count.

AI-vs-human attribution
-----------------------

The AI handler writes outbound rows with ``sender_user_id IS NULL``
and ``payload->>'author' = 'ai'``. Everywhere we need to count human
work (response time, leaderboard) we use::

    direction = 'out'
    AND sender_user_id IS NOT NULL
    AND is_internal = false

…which naturally excludes AI replies + internal notes. The volume
widget counts AI-vs-human in a separate dimension so the dashboard
can show both.

Query budget
------------

Each call returns at most 100 buckets / rows; the SQL caps with
``LIMIT 100`` and the date range is clamped to ``90`` days
upstream. For 100K+ msg/month orgs we'll add a materialized view
(``tbl_whatsapp_daily_rollup``) and a refresh task — deferred until
real volume warrants it (mentioned in the step risks).

RLS scoping
-----------

The ``app.org_id`` Postgres setting is applied on every transaction
via the SQLAlchemy ``after_begin`` hook; we additionally pass
``org_id`` into each query as a belt-and-braces filter so a missing
RLS policy can't accidentally leak. Numbers reported are tenant-
isolated either way.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


RangeKey = Literal["7d", "30d", "90d"]
GranularityKey = Literal["day", "hour"]
ResponseTimeGroupBy = Literal["agent", "team", "channel"]


_RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


def _resolve_range(range_key: str) -> tuple[datetime, datetime]:
    """Return ``(start_utc, end_utc)`` for the named window.

    ``end`` is "now" (UTC); ``start`` is N days back. We always work
    in UTC at the SQL layer — the SPA converts to the viewer's
    locale at display time."""
    days = _RANGE_DAYS.get(range_key)
    if days is None:
        raise ValueError(
            f"range must be one of {sorted(_RANGE_DAYS)}, got {range_key!r}"
        )
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start, end


def _resolve_granularity(
    granularity: str, range_key: str
) -> str:
    """Validate the granularity choice against the range.

    Hour-buckets only make sense for short ranges — 90d * 24h = 2160
    buckets, well past the 100-cap, so we reject ``hour`` for the
    90d range. Day works for everything."""
    if granularity not in ("day", "hour"):
        raise ValueError(
            f"granularity must be 'day' or 'hour', got {granularity!r}"
        )
    if granularity == "hour" and range_key == "90d":
        raise ValueError(
            "hour granularity not supported for 90d range "
            "(use day or shorten the range)"
        )
    return granularity


# ---------------------------------------------------------------------------
# Result dataclasses (lightweight — Pydantic schemas wrap these at the
# router boundary so we don't import Pydantic into the service layer).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolumeBucket:
    bucket_start: datetime
    sent: int
    received: int
    failed: int
    ai_sent: int


@dataclass(frozen=True, slots=True)
class VolumeReport:
    range: str
    granularity: str
    buckets: list[VolumeBucket]
    total_sent: int
    total_received: int
    total_failed: int
    total_ai_sent: int


@dataclass(frozen=True, slots=True)
class ResponseTimeBucket:
    """Distribution bucket for the histogram chart."""

    label: str
    seconds_lt: int  # upper bound (exclusive), or -1 for the catch-all
    count: int


@dataclass(frozen=True, slots=True)
class ResponseTimeGroup:
    """Per-agent or per-team breakdown."""

    key: str  # user id / team id / channel
    label: str
    median_seconds: Optional[float]
    p95_seconds: Optional[float]
    sample_size: int


@dataclass(frozen=True, slots=True)
class ResponseTimeReport:
    range: str
    groupby: str
    overall_median_seconds: Optional[float]
    overall_p95_seconds: Optional[float]
    sample_size: int
    distribution: list[ResponseTimeBucket]
    groups: list[ResponseTimeGroup]


@dataclass(frozen=True, slots=True)
class OutcomeSlice:
    key: str  # status value or tag id
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class OutcomesReport:
    range: str
    by_status: list[OutcomeSlice]
    by_tag: list[OutcomeSlice]
    total: int


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    user_id: uuid.UUID
    name: str
    replies: int
    conversations_handled: int
    median_response_seconds: Optional[float]
    p95_response_seconds: Optional[float]


@dataclass(frozen=True, slots=True)
class LeaderboardReport:
    range: str
    rows: list[LeaderboardRow]


# ---------------------------------------------------------------------------
# Volume (sent / received / failed) bucketed by date
# ---------------------------------------------------------------------------


async def compute_volume(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "7d",
    granularity: str = "day",
) -> VolumeReport:
    """Count messages bucketed by date_trunc(granularity, created_at).

    AI replies are split into their own column so the dashboard can
    answer "how much of our outbound is bot-driven?" without a second
    query. "failed" means the outbound row has a ``payload->>'meta_status'``
    of ``failed`` (set by the delivery webhook in Phase 3.5)."""
    start, end = _resolve_range(range_key)
    granularity = _resolve_granularity(granularity, range_key)

    stmt = text(
        f"""
        SELECT
            date_trunc(:granularity, m.created_at AT TIME ZONE 'UTC')
                AS bucket_start,
            SUM(CASE WHEN m.direction = 'out'
                      AND m.is_internal = false
                      AND COALESCE(m.payload->>'author','') <> 'ai'
                     THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN m.direction = 'in'  THEN 1 ELSE 0 END) AS received,
            SUM(CASE WHEN m.direction = 'out'
                      AND COALESCE(m.payload->>'meta_status','') = 'failed'
                     THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN m.direction = 'out'
                      AND COALESCE(m.payload->>'author','') = 'ai'
                     THEN 1 ELSE 0 END) AS ai_sent
        FROM tbl_messages m
        JOIN tbl_conversations c ON c.id = m.conversation_id
        WHERE m.org_id = :org_id
          AND c.channel = 'whatsapp'
          AND m.created_at >= :start
          AND m.created_at <  :end
        GROUP BY 1
        ORDER BY 1 ASC
        LIMIT 100
        """
    )
    rows = (
        await session.execute(
            stmt,
            {
                "org_id": org_id,
                "start": start,
                "end": end,
                "granularity": granularity,
            },
        )
    ).all()

    buckets: list[VolumeBucket] = []
    total_sent = total_received = total_failed = total_ai = 0
    for r in rows:
        sent = int(r.sent or 0)
        received = int(r.received or 0)
        failed = int(r.failed or 0)
        ai_sent = int(r.ai_sent or 0)
        bucket_start = r.bucket_start
        if bucket_start.tzinfo is None:
            bucket_start = bucket_start.replace(tzinfo=timezone.utc)
        buckets.append(
            VolumeBucket(
                bucket_start=bucket_start,
                sent=sent,
                received=received,
                failed=failed,
                ai_sent=ai_sent,
            )
        )
        total_sent += sent
        total_received += received
        total_failed += failed
        total_ai += ai_sent

    return VolumeReport(
        range=range_key,
        granularity=granularity,
        buckets=buckets,
        total_sent=total_sent,
        total_received=total_received,
        total_failed=total_failed,
        total_ai_sent=total_ai,
    )


# ---------------------------------------------------------------------------
# Response time (median + p95 + distribution + per-group breakdown)
# ---------------------------------------------------------------------------


_DISTRIBUTION_BUCKETS: list[tuple[str, int]] = [
    ("< 1 min", 60),
    ("1–5 min", 300),
    ("5–15 min", 900),
    ("15–60 min", 3600),
    ("1–4 hr", 14400),
    ("4–24 hr", 86400),
    ("> 24 hr", -1),
]


def _label_for_seconds(seconds: float) -> str:
    for label, upper in _DISTRIBUTION_BUCKETS:
        if upper == -1 or seconds < upper:
            return label
    return _DISTRIBUTION_BUCKETS[-1][0]


async def compute_response_time(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "7d",
    groupby: str = "agent",
) -> ResponseTimeReport:
    """Time-to-first-staff-reply per conversation in the window.

    "First staff reply" = the earliest outbound message on a
    conversation by a *human* user (``sender_user_id IS NOT NULL``,
    ``is_internal = false``). AI replies never count toward this
    metric — they belong on the AI dashboard.

    Conversations that received only AI replies (or no reply at all)
    contribute zero samples here, which keeps the median honest."""
    start, end = _resolve_range(range_key)
    if groupby not in ("agent", "team", "channel"):
        raise ValueError(
            f"groupby must be 'agent', 'team', or 'channel', got {groupby!r}"
        )

    # Per-conversation: first inbound time + first human staff reply
    # time + the user who replied. We compute the delta in seconds in
    # Python so the percentile + bucket code stays readable.
    stmt = text(
        """
        WITH first_inbound AS (
            SELECT m.conversation_id,
                   MIN(m.created_at) AS ts
            FROM tbl_messages m
            JOIN tbl_conversations c ON c.id = m.conversation_id
            WHERE m.org_id = :org_id
              AND c.channel = 'whatsapp'
              AND m.direction = 'in'
              AND m.created_at >= :start
              AND m.created_at <  :end
            GROUP BY m.conversation_id
        ),
        first_reply AS (
            SELECT m.conversation_id,
                   MIN(m.created_at) AS ts,
                   (ARRAY_AGG(m.sender_user_id ORDER BY m.created_at ASC))[1]
                       AS sender_user_id
            FROM tbl_messages m
            JOIN tbl_conversations c ON c.id = m.conversation_id
            WHERE m.org_id = :org_id
              AND c.channel = 'whatsapp'
              AND m.direction = 'out'
              AND m.is_internal = false
              AND m.sender_user_id IS NOT NULL
              AND m.created_at >= :start
              AND m.created_at <  :end
            GROUP BY m.conversation_id
        )
        SELECT
            fi.conversation_id,
            EXTRACT(EPOCH FROM (fr.ts - fi.ts)) AS seconds,
            fr.sender_user_id
        FROM first_inbound fi
        JOIN first_reply fr ON fr.conversation_id = fi.conversation_id
        WHERE fr.ts > fi.ts
        LIMIT 5000
        """
    )
    rows = (
        await session.execute(
            stmt,
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    overall_samples: list[float] = []
    per_agent: dict[uuid.UUID, list[float]] = {}
    for r in rows:
        seconds = float(r.seconds or 0)
        if seconds < 0:
            continue
        overall_samples.append(seconds)
        if r.sender_user_id is not None:
            per_agent.setdefault(r.sender_user_id, []).append(seconds)

    # Distribution
    dist_counts = {label: 0 for label, _ in _DISTRIBUTION_BUCKETS}
    for s in overall_samples:
        dist_counts[_label_for_seconds(s)] += 1
    distribution = [
        ResponseTimeBucket(label=label, seconds_lt=upper, count=dist_counts[label])
        for label, upper in _DISTRIBUTION_BUCKETS
    ]

    overall_median = _percentile(overall_samples, 0.5)
    overall_p95 = _percentile(overall_samples, 0.95)

    groups: list[ResponseTimeGroup] = []
    if groupby == "agent" and per_agent:
        ids = list(per_agent.keys())
        names = await _resolve_user_names(session, ids)
        for user_id, samples in per_agent.items():
            groups.append(
                ResponseTimeGroup(
                    key=str(user_id),
                    label=names.get(user_id, "Unknown"),
                    median_seconds=_percentile(samples, 0.5),
                    p95_seconds=_percentile(samples, 0.95),
                    sample_size=len(samples),
                )
            )
        groups.sort(
            key=lambda g: (g.median_seconds if g.median_seconds is not None else float("inf"))
        )
    # `team` + `channel` groupings are present in the schema for
    # future expansion (Phase 3.6 multi-channel + the teams module);
    # current scope is single-team / WA-only so they're empty.

    return ResponseTimeReport(
        range=range_key,
        groupby=groupby,
        overall_median_seconds=overall_median,
        overall_p95_seconds=overall_p95,
        sample_size=len(overall_samples),
        distribution=distribution,
        groups=groups,
    )


def _percentile(samples: list[float], q: float) -> Optional[float]:
    """Lightweight percentile — no numpy dep for one analytics call.

    `q` is in 0..1. Uses linear interpolation between adjacent ranks
    (the same definition as numpy's default `linear` method). Returns
    None on an empty sample set so the SPA can show "—" instead of 0."""
    if not samples:
        return None
    if len(samples) == 1:
        return float(samples[0])
    s = sorted(samples)
    pos = (len(s) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(s) - 1)
    frac = pos - lower
    return float(s[lower] + (s[upper] - s[lower]) * frac)


async def _resolve_user_names(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Map ``legacy_uuid`` -> display name via tbl_user_info.

    The leaderboard + per-agent grouping need human-readable labels.
    Falls back to a partial name when only one of first/last exists,
    or "Unknown user" if the row is gone (deactivated + scrubbed)."""
    if not user_ids:
        return {}
    stmt = text(
        """
        SELECT u.legacy_uuid AS user_id,
               COALESCE(i.first_name, '') AS first_name,
               COALESCE(i.last_name, '')  AS last_name
        FROM tbl_user_login u
        JOIN tbl_user_info i ON i.member_id = u.id
        WHERE u.legacy_uuid = ANY(:ids)
        """
    )
    rows = (
        await session.execute(stmt, {"ids": list(user_ids)})
    ).all()
    out: dict[uuid.UUID, str] = {}
    for r in rows:
        name = f"{r.first_name} {r.last_name}".strip()
        if not name:
            name = "Unknown"
        out[r.user_id] = name
    for uid in user_ids:
        out.setdefault(uid, "Unknown")
    return out


# ---------------------------------------------------------------------------
# Outcomes — conversation status distribution + tag breakdown
# ---------------------------------------------------------------------------


async def compute_outcomes(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "7d",
) -> OutcomesReport:
    """Distribution of conversation ``status`` + top tag breakdown.

    Counts every WhatsApp conversation whose ``last_message_at`` falls
    within the range — that's the field the inbox sorts on, so it's
    the natural "active in the period" filter. Closed-and-untouched
    conversations from before the range correctly don't appear."""
    start, end = _resolve_range(range_key)

    status_stmt = text(
        """
        SELECT c.status::text AS status, COUNT(*) AS n
        FROM tbl_conversations c
        WHERE c.org_id = :org_id
          AND c.channel = 'whatsapp'
          AND c.last_message_at >= :start
          AND c.last_message_at <  :end
        GROUP BY c.status
        ORDER BY n DESC
        """
    )
    status_rows = (
        await session.execute(
            status_stmt,
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()
    by_status: list[OutcomeSlice] = []
    total = 0
    for r in status_rows:
        n = int(r.n or 0)
        by_status.append(
            OutcomeSlice(
                key=str(r.status), label=str(r.status).title(), count=n
            )
        )
        total += n

    tag_stmt = text(
        """
        SELECT t.id::text AS tag_id, t.name AS tag_name, COUNT(*) AS n
        FROM tbl_conversation_tag_assignments a
        JOIN tbl_conversations c ON c.id = a.conversation_id
        JOIN tbl_conversation_tags t ON t.id = a.tag_id
        WHERE a.org_id = :org_id
          AND c.channel = 'whatsapp'
          AND c.last_message_at >= :start
          AND c.last_message_at <  :end
        GROUP BY t.id, t.name
        ORDER BY n DESC
        LIMIT 20
        """
    )
    tag_rows = (
        await session.execute(
            tag_stmt,
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()
    by_tag = [
        OutcomeSlice(
            key=str(r.tag_id), label=str(r.tag_name), count=int(r.n or 0)
        )
        for r in tag_rows
    ]

    return OutcomesReport(
        range=range_key, by_status=by_status, by_tag=by_tag, total=total
    )


# ---------------------------------------------------------------------------
# Agent leaderboard
# ---------------------------------------------------------------------------


async def compute_agent_leaderboard(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "7d",
) -> LeaderboardReport:
    """Per-agent reply count + conversations handled + response-time
    percentiles.

    "Conversations handled" = distinct conversations the agent sent
    at least one outbound human reply on in the window. AI-only
    conversations (no human replier) contribute to no agent's
    leaderboard row.

    Sort order: median response time ascending. Agents tied at "no
    samples" sort to the end so the dashboard reads "fastest →
    slowest → silent"."""
    start, end = _resolve_range(range_key)

    # Per-agent reply count + distinct conversation count.
    counts_stmt = text(
        """
        SELECT m.sender_user_id AS user_id,
               COUNT(*) AS replies,
               COUNT(DISTINCT m.conversation_id) AS conversations
        FROM tbl_messages m
        JOIN tbl_conversations c ON c.id = m.conversation_id
        WHERE m.org_id = :org_id
          AND c.channel = 'whatsapp'
          AND m.direction = 'out'
          AND m.is_internal = false
          AND m.sender_user_id IS NOT NULL
          AND m.created_at >= :start
          AND m.created_at <  :end
        GROUP BY m.sender_user_id
        """
    )
    counts_rows = (
        await session.execute(
            counts_stmt,
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    # Per-agent response-time samples — reuse the same first-inbound
    # → first-staff-reply join as `compute_response_time` so the
    # numbers reconcile.
    rt_stmt = text(
        """
        WITH first_inbound AS (
            SELECT m.conversation_id, MIN(m.created_at) AS ts
            FROM tbl_messages m
            JOIN tbl_conversations c ON c.id = m.conversation_id
            WHERE m.org_id = :org_id
              AND c.channel = 'whatsapp'
              AND m.direction = 'in'
              AND m.created_at >= :start
              AND m.created_at <  :end
            GROUP BY m.conversation_id
        ),
        first_reply AS (
            SELECT m.conversation_id,
                   MIN(m.created_at) AS ts,
                   (ARRAY_AGG(m.sender_user_id ORDER BY m.created_at ASC))[1]
                       AS sender_user_id
            FROM tbl_messages m
            JOIN tbl_conversations c ON c.id = m.conversation_id
            WHERE m.org_id = :org_id
              AND c.channel = 'whatsapp'
              AND m.direction = 'out'
              AND m.is_internal = false
              AND m.sender_user_id IS NOT NULL
              AND m.created_at >= :start
              AND m.created_at <  :end
            GROUP BY m.conversation_id
        )
        SELECT fr.sender_user_id AS user_id,
               EXTRACT(EPOCH FROM (fr.ts - fi.ts)) AS seconds
        FROM first_inbound fi
        JOIN first_reply fr ON fr.conversation_id = fi.conversation_id
        WHERE fr.ts > fi.ts
        LIMIT 5000
        """
    )
    rt_rows = (
        await session.execute(
            rt_stmt,
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    per_agent_samples: dict[uuid.UUID, list[float]] = {}
    for r in rt_rows:
        if r.user_id is None:
            continue
        per_agent_samples.setdefault(r.user_id, []).append(
            float(r.seconds or 0)
        )

    # Combine the two passes. The "counts" pass is the source of
    # truth for who shows up (anyone with ≥ 1 reply); samples is a
    # left-join (None when the agent only sent follow-ups, never the
    # first reply).
    user_ids: list[uuid.UUID] = [
        r.user_id for r in counts_rows if r.user_id is not None
    ]
    names = await _resolve_user_names(session, user_ids)

    rows: list[LeaderboardRow] = []
    for r in counts_rows:
        if r.user_id is None:
            continue
        samples = per_agent_samples.get(r.user_id, [])
        rows.append(
            LeaderboardRow(
                user_id=r.user_id,
                name=names.get(r.user_id, "Unknown"),
                replies=int(r.replies or 0),
                conversations_handled=int(r.conversations or 0),
                median_response_seconds=_percentile(samples, 0.5),
                p95_response_seconds=_percentile(samples, 0.95),
            )
        )
    rows.sort(
        key=lambda x: (
            x.median_response_seconds
            if x.median_response_seconds is not None
            else float("inf"),
            -x.replies,
        )
    )
    return LeaderboardReport(range=range_key, rows=rows[:100])


__all__ = [
    "RangeKey",
    "GranularityKey",
    "ResponseTimeGroupBy",
    "VolumeReport",
    "VolumeBucket",
    "ResponseTimeReport",
    "ResponseTimeBucket",
    "ResponseTimeGroup",
    "OutcomesReport",
    "OutcomeSlice",
    "LeaderboardReport",
    "LeaderboardRow",
    "compute_volume",
    "compute_response_time",
    "compute_outcomes",
    "compute_agent_leaderboard",
]
