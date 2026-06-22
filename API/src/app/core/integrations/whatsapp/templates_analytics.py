"""Per-template performance aggregation
(whatsapp-platform-upgrade Step 10).

Single entry point — :func:`get_template_performance` — returns the
shape rendered by the frontend performance card:

  * Headline counts: sent / delivered / read / replied / click_through
    / failed
  * Derived rates: delivery / read / reply (capped at 100, rounded to
    1 decimal place, 0.0 when the denominator is 0)
  * Daily buckets for the sparkline + line chart (cap of 100 buckets)
  * Grouped failure reasons mapped from Meta error text into operator-
    actionable buckets (rate-limited / opted-out / invalid number /
    template paused / other)
  * Used-in-campaigns count + recent ids for the
    "Used in N campaigns" link

Source tables: ``tbl_campaign_messages`` (delivery state + failure
text) joined to ``tbl_campaigns`` (template_id), plus
``tbl_messages`` for inbound replies / button taps. RLS auto-scopes
all reads to the active org via ``TenantScoped``.

No SQL injection vectors: every input is a UUID or an int range
clamped to the documented values.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.campaigns.models import (
    Campaign,
    CampaignMessage,
    CampaignMessageStatus,
)
from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
    MessageDirection,
)


RangeKey = Literal["7d", "30d", "90d"]

_RANGE_TO_DAYS: dict[RangeKey, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}


@dataclass(frozen=True, slots=True)
class DailyBucket:
    """One day-grain bucket on the line chart."""

    date: str  # YYYY-MM-DD
    sent: int
    delivered: int
    read: int
    failed: int


@dataclass(frozen=True, slots=True)
class FailureGroup:
    """One grouped failure reason on the breakdown table."""

    bucket: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class TemplatePerformance:
    """Aggregated per-template stats for the performance card."""

    template_id: uuid.UUID
    range_key: RangeKey
    range_start: datetime
    range_end: datetime

    sent: int
    delivered: int
    read: int
    replied: int
    click_through: int
    failed: int

    delivery_rate: float
    read_rate: float
    reply_rate: float

    daily: list[DailyBucket] = field(default_factory=list)
    failures: list[FailureGroup] = field(default_factory=list)
    used_in_campaigns: int = 0


# --- helpers --------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float:
    """Percent rate rounded to 1 decimal place. 0.0 when denominator is 0.

    Capped at 100 so a stale read/delivery row that races ahead of
    its sent record doesn't surface as 102%."""
    if denominator <= 0:
        return 0.0
    raw = (numerator * 100.0) / denominator
    return round(min(raw, 100.0), 1)


# Meta error message → operator-actionable bucket. The strings are
# substrings of what we see in `tbl_campaign_messages.error` after
# the webhook lands; matching is case-insensitive and short-circuits
# on the first hit per row. New Meta errors fall to "other" — easy
# to add a bucket here without a migration.
_FAILURE_RULES: list[tuple[str, str, str]] = [
    ("rate_limited", "Rate limited", "rate"),
    ("rate_limited", "Rate limited", "throttle"),
    ("opted_out", "Recipient opted out", "opted"),
    ("opted_out", "Recipient opted out", "opt-out"),
    ("opted_out", "Recipient opted out", "blocked"),
    ("invalid_number", "Invalid number", "invalid"),
    ("invalid_number", "Invalid number", "unknown"),
    ("invalid_number", "Invalid number", "not exist"),
    ("template_paused", "Template paused", "paused"),
    ("template_paused", "Template paused", "disabled"),
    ("template_paused", "Template paused", "unauthorized"),
]


def _classify_failure(text: str | None) -> tuple[str, str]:
    """Map a free-text Meta error to ``(bucket, label)``. Returns
    ``('other', 'Other')`` for anything not matched."""
    if not text:
        return ("other", "Other")
    lower = text.lower()
    for bucket, label, needle in _FAILURE_RULES:
        if needle in lower:
            return (bucket, label)
    return ("other", "Other")


# --- main aggregator ------------------------------------------------------


async def get_template_performance(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    range_key: RangeKey,
) -> TemplatePerformance:
    """Compute the performance card payload for one template.

    Empty-state friendly: returns a row with all-zero counts and an
    empty daily list when no campaign has ever used the template.
    The 0-bucket failure list signals "no failures yet" rather than
    "couldn't compute"."""
    days = _RANGE_TO_DAYS[range_key]
    now = datetime.now(timezone.utc)
    range_start = now - timedelta(days=days)

    # All CampaignMessage rows that belong to a campaign using this
    # template AND landed inside the range. Joining at the application
    # layer (instead of subquery) so RLS scopes both tables uniformly.
    rows = (
        await session.execute(
            select(
                CampaignMessage.id,
                CampaignMessage.contact_id,
                CampaignMessage.status,
                CampaignMessage.error,
                CampaignMessage.sent_at,
                CampaignMessage.delivered_at,
                CampaignMessage.read_at,
                CampaignMessage.created_at,
                CampaignMessage.campaign_id,
            )
            .join(Campaign, Campaign.id == CampaignMessage.campaign_id)
            .where(Campaign.template_id == template_id)
            .where(CampaignMessage.created_at >= range_start)
            # Cap at 100k rows to keep aggregation snappy; bigger orgs
            # fall back to the (forthcoming) Step-21 analytics surface.
            .limit(100_000)
        )
    ).all()

    sent = 0
    delivered = 0
    read = 0
    failed = 0
    daily: dict[str, dict[str, int]] = {}
    failures_counter: dict[str, dict[str, Any]] = {}
    contact_ids: set[uuid.UUID] = set()

    for row in rows:
        contact_ids.add(row.contact_id)
        # Sent count includes every row that's at-least-queued
        # successfully (Meta accepted the dispatch). Failed-only rows
        # don't count toward sent — they count toward failed only.
        if row.status != CampaignMessageStatus.failed:
            sent += 1
        if row.delivered_at is not None:
            delivered += 1
        if row.read_at is not None:
            read += 1
        if row.status == CampaignMessageStatus.failed:
            failed += 1
            bucket, label = _classify_failure(row.error)
            slot = failures_counter.setdefault(
                bucket, {"label": label, "count": 0}
            )
            slot["count"] += 1

        date_key = row.created_at.date().isoformat()
        bucket_day = daily.setdefault(
            date_key,
            {"sent": 0, "delivered": 0, "read": 0, "failed": 0},
        )
        if row.status != CampaignMessageStatus.failed:
            bucket_day["sent"] += 1
        if row.delivered_at is not None:
            bucket_day["delivered"] += 1
        if row.read_at is not None:
            bucket_day["read"] += 1
        if row.status == CampaignMessageStatus.failed:
            bucket_day["failed"] += 1

    # Inbound replies + button taps from the same contacts in the same
    # window. We don't try to attribute a specific reply to a specific
    # outbound message — the spec is "did this contact reply to a
    # campaign using this template, within the window." Coarser than
    # Step 21's per-message attribution; honest for the MVP.
    replied = 0
    click_through = 0
    if contact_ids:
        reply_rows = (
            await session.execute(
                select(
                    Message.id,
                    Message.attachments,
                )
                .join(
                    Conversation, Conversation.id == Message.conversation_id
                )
                .where(Conversation.channel == ConversationChannel.whatsapp)
                .where(Conversation.contact_id.in_(contact_ids))
                .where(Message.direction == MessageDirection.in_)
                .where(Message.created_at >= range_start)
                .limit(100_000)
            )
        ).all()
        for r in reply_rows:
            replied += 1
            # A reply attribution attachment (Step 6) marks a button /
            # list tap. The shape was set by parse_webhook —
            # `{type:'reply', reply_kind:'button'|'list', ...}`.
            for att in r.attachments or []:
                if isinstance(att, dict) and att.get("type") == "reply":
                    click_through += 1
                    break

    # Campaigns-using-this-template count (range-wide; we don't filter
    # by created_at on Campaign — operators want the total "how often
    # have I shipped this" number, not just the time-windowed slice).
    used_in_campaigns = (
        await session.execute(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.template_id == template_id)
        )
    ).scalar_one() or 0

    failure_groups = sorted(
        (
            FailureGroup(bucket=k, label=v["label"], count=v["count"])
            for k, v in failures_counter.items()
        ),
        key=lambda f: f.count,
        reverse=True,
    )

    # Render daily buckets in date order so the chart doesn't zig-zag.
    daily_buckets = [
        DailyBucket(
            date=date_key,
            sent=v["sent"],
            delivered=v["delivered"],
            read=v["read"],
            failed=v["failed"],
        )
        for date_key, v in sorted(daily.items())
    ]
    # Hard cap to protect the JSON wire and the chart renderer. 100
    # buckets covers 90d cleanly; for ranges where Meta lets us look
    # further back we'll downsample at that point.
    if len(daily_buckets) > 100:
        daily_buckets = daily_buckets[-100:]

    return TemplatePerformance(
        template_id=template_id,
        range_key=range_key,
        range_start=range_start,
        range_end=now,
        sent=sent,
        delivered=delivered,
        read=read,
        replied=replied,
        click_through=click_through,
        failed=failed,
        delivery_rate=_rate(delivered, sent),
        read_rate=_rate(read, sent),
        reply_rate=_rate(replied, sent),
        daily=daily_buckets,
        failures=failure_groups,
        used_in_campaigns=int(used_in_campaigns),
    )


__all__ = [
    "DailyBucket",
    "FailureGroup",
    "RangeKey",
    "TemplatePerformance",
    "_classify_failure",
    "get_template_performance",
]
