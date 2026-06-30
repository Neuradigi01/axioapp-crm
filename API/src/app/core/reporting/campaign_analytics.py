"""Campaign + org-wide WhatsApp analytics
(whatsapp-platform-upgrade Step 21).

Six aggregation functions powering the analytics dashboards:

  * ``compute_campaign_funnel`` — per-campaign targeted → sent →
    delivered → read → replied → converted breakdown + time-to-
    delivery percentiles.
  * ``compute_campaign_failures`` — classifies the ``error`` text
    column on ``tbl_campaign_messages`` into the Step-21 taxonomy
    and counts each bucket.
  * ``compute_cost`` — sums outbound row counts grouped by Meta
    pricing category, multiplies through ``cost_estimator``.
  * ``compute_quality_timeline`` — phone health events from
    Step 12 + daily WhatsApp send volume so dashboards can overlay
    drops with traffic spikes.
  * ``compute_ai_metrics`` — AI response rate + escalation rate +
    AI-only completion proxy.

Conversion attribution
----------------------

The lead table carries an ``attribution`` JSONB column from
migration 0045. Convention: store
``{"source_campaign_id": "<uuid>"}`` at lead-create time when the
lead originated from a campaign. The 7-day attribution window is
hardcoded; it's the same number Phase 4.2 picked for the funnel
spec — making it configurable is parked for Step 21's risks list.

AI vs human
-----------

Outbound rows with ``payload->>'author' = 'ai'`` are AI replies
(Step 19). Counted as the AI bucket in the AI metrics widget and
under the ``service`` cost category (the 24-hour customer-
initiated window is free, and conversational AI replies all sit
inside that window).

RLS scoping
-----------

``app.org_id`` is set on every transaction (Step 1.4 hook). Each
query additionally passes ``org_id`` as a belt-and-braces filter so
a missing RLS policy can't leak across tenants.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.reporting import cost_estimator
from src.app.core.reporting.whatsapp_analytics import (
    _percentile,
    _resolve_range,
)

logger = logging.getLogger(__name__)


# Step 21 plan #2 — failure taxonomy. The order matches the UI's
# table so the cost dashboard groups consistently with the campaign
# detail page.
FAILURE_REASONS: tuple[str, ...] = (
    "rate_limited",
    "invalid_number",
    "opted_out",
    "template_paused",
    "quality_restricted",
    "other",
)


_CONVERSION_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Result dataclasses (lightweight; the router wraps them in
# `from_attributes=True` Pydantic models at the boundary).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FunnelStage:
    key: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class CampaignFunnelReport:
    campaign_id: uuid.UUID
    name: str
    status: str
    started_at: datetime | None
    stages: list[FunnelStage]
    delivery_median_seconds: float | None
    delivery_p95_seconds: float | None


@dataclass(frozen=True, slots=True)
class FailureBucket:
    reason: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class CampaignFailuresReport:
    campaign_id: uuid.UUID
    total_failed: int
    buckets: list[FailureBucket]
    sample_errors: list[str]


@dataclass(frozen=True, slots=True)
class CostLineOut:
    category: str
    count: int
    rate: float
    currency: str
    total: float


@dataclass(frozen=True, slots=True)
class CostReport:
    range: str
    region: str
    currency: str
    lines: list[CostLineOut]
    total: float
    is_estimate: bool


@dataclass(frozen=True, slots=True)
class QualityEvent:
    occurred_at: datetime
    event_type: str
    old_value: str | None
    new_value: str | None


@dataclass(frozen=True, slots=True)
class QualityVolumePoint:
    bucket_start: datetime
    sent: int


@dataclass(frozen=True, slots=True)
class QualityTimelineReport:
    range: str
    events: list[QualityEvent]
    volume: list[QualityVolumePoint]


@dataclass(frozen=True, slots=True)
class AIMetricsReport:
    range: str
    ai_replies: int
    human_replies: int
    ai_response_rate: float
    ai_handled_conversations: int
    escalated_conversations: int
    escalation_rate: float
    ai_only_completed: int
    escalation_reasons: dict[str, int]


# ---------------------------------------------------------------------------
# Failure-reason classifier
# ---------------------------------------------------------------------------


def _classify_failure(error: str | None) -> str:
    """Map Meta's ``error`` title onto the Step-21 taxonomy.

    Meta's error titles are stable strings — we match on lowercased
    substrings. Unknown errors land in "other"; the dashboard
    surfaces ``sample_errors`` so the operator can eyeball anything
    that's not classified."""
    if not error:
        return "other"
    e = str(error).lower()
    if "rate" in e and ("limit" in e or "throttl" in e):
        return "rate_limited"
    if "not on whatsapp" in e or "invalid" in e or "non-existing" in e or "wa id" in e:
        return "invalid_number"
    if "opted out" in e or "user has not opted in" in e or "consent" in e:
        return "opted_out"
    if "template" in e and ("paused" in e or "disabled" in e or "rejected" in e or "deleted" in e):
        return "template_paused"
    if (
        "quality" in e
        or "messaging limit" in e
        or "tier" in e
        or "blocked" in e
        or "restricted" in e
    ):
        return "quality_restricted"
    return "other"


_FAILURE_LABELS: dict[str, str] = {
    "rate_limited": "Rate limited",
    "invalid_number": "Invalid / not on WhatsApp",
    "opted_out": "Opted out / no consent",
    "template_paused": "Template paused / rejected",
    "quality_restricted": "Quality restricted",
    "other": "Other",
}


def _funnel_label(key: str) -> str:
    return {
        "targeted": "Targeted",
        "sent": "Sent",
        "delivered": "Delivered",
        "read": "Read",
        "replied": "Replied",
        "converted": "Converted",
        "failed": "Failed",
    }.get(key, key.title())


# ---------------------------------------------------------------------------
# Campaign funnel
# ---------------------------------------------------------------------------


async def compute_campaign_funnel(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> CampaignFunnelReport | None:
    """Per-campaign funnel + time-to-delivery percentiles.

    Funnel stages (in order):

      * targeted — every row in tbl_campaign_messages.
      * sent — status in (sent, delivered, read).
      * delivered — status in (delivered, read).
      * read — status = read.
      * replied — distinct contacts who messaged back within the
        7-day attribution window.
      * converted — leads carrying
        attribution->>'source_campaign_id' = campaign_id created
        within 7 days of message receipt.
      * failed — status = failed (also surfaced separately on the
        failures endpoint).
    """
    head = (
        await session.execute(
            text(
                """
                SELECT id, name, status::text AS status,
                       schedule_at AS started_at, created_at
                FROM tbl_campaigns
                WHERE id = :cid AND org_id = :org_id
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).first()
    if head is None:
        return None

    counts = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS targeted,
                    SUM(CASE WHEN status IN ('sent','delivered','read')
                             THEN 1 ELSE 0 END) AS sent,
                    SUM(CASE WHEN status IN ('delivered','read')
                             THEN 1 ELSE 0 END) AS delivered,
                    SUM(CASE WHEN status = 'read' THEN 1 ELSE 0 END) AS read,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM tbl_campaign_messages
                WHERE campaign_id = :cid AND org_id = :org_id
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).first()

    # "Replied" — count distinct contacts who sent an inbound message
    # after the campaign started. We bound the window with the 7-day
    # conversion span to keep the metric honest (otherwise an unrelated
    # conversation months later would count).
    window_end_expr = "now()"
    replied_row = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT cm.contact_id) AS replied
                FROM tbl_campaign_messages cm
                JOIN tbl_contacts ct ON ct.id = cm.contact_id
                JOIN tbl_conversations c ON c.contact_id = ct.id
                JOIN tbl_messages m
                     ON m.conversation_id = c.id
                    AND m.direction = 'in'
                WHERE cm.campaign_id = :cid
                  AND cm.org_id = :org_id
                  AND cm.sent_at IS NOT NULL
                  AND m.created_at >  cm.sent_at
                  AND m.created_at <= cm.sent_at + INTERVAL '{_CONVERSION_WINDOW_DAYS} days'
                  AND m.created_at <= {window_end_expr}
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).first()

    converted_row = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(*) AS converted
                FROM tbl_leads l
                JOIN tbl_campaign_messages cm
                     ON cm.contact_id = l.contact_id
                WHERE cm.campaign_id = :cid
                  AND cm.org_id = :org_id
                  AND cm.sent_at IS NOT NULL
                  AND l.attribution IS NOT NULL
                  AND l.attribution->>'source_campaign_id' = :cid_text
                  AND l.created_at BETWEEN cm.sent_at
                                       AND cm.sent_at + INTERVAL '{_CONVERSION_WINDOW_DAYS} days'
                """
            ),
            {
                "cid": campaign_id,
                "cid_text": str(campaign_id),
                "org_id": org_id,
            },
        )
    ).first()

    deltas_rows = (
        await session.execute(
            text(
                """
                SELECT EXTRACT(EPOCH FROM (delivered_at - sent_at)) AS seconds
                FROM tbl_campaign_messages
                WHERE campaign_id = :cid AND org_id = :org_id
                  AND sent_at IS NOT NULL AND delivered_at IS NOT NULL
                  AND delivered_at > sent_at
                LIMIT 5000
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).all()
    seconds_samples = [float(r.seconds) for r in deltas_rows if r.seconds is not None]

    targeted = int(counts.targeted or 0)
    sent = int(counts.sent or 0)
    delivered = int(counts.delivered or 0)
    read_n = int(counts.read or 0)
    failed = int(counts.failed or 0)
    replied = int((replied_row.replied if replied_row else 0) or 0)
    converted = int((converted_row.converted if converted_row else 0) or 0)

    stages = [
        FunnelStage(key=k, label=_funnel_label(k), count=v)
        for k, v in (
            ("targeted", targeted),
            ("sent", sent),
            ("delivered", delivered),
            ("read", read_n),
            ("replied", replied),
            ("converted", converted),
            ("failed", failed),
        )
    ]

    started_at = head.started_at
    if started_at is not None and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    return CampaignFunnelReport(
        campaign_id=campaign_id,
        name=head.name,
        status=head.status,
        started_at=started_at,
        stages=stages,
        delivery_median_seconds=_percentile(seconds_samples, 0.5),
        delivery_p95_seconds=_percentile(seconds_samples, 0.95),
    )


# ---------------------------------------------------------------------------
# Campaign failures
# ---------------------------------------------------------------------------


async def compute_campaign_failures(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> CampaignFailuresReport:
    """Failure reason breakdown for a single campaign.

    Pulls every ``status='failed'`` row + its ``error`` text and
    classifies in Python. Sample of up to 5 raw error strings is
    returned so the operator can drill into "other"."""
    rows = (
        await session.execute(
            text(
                """
                SELECT error
                FROM tbl_campaign_messages
                WHERE campaign_id = :cid AND org_id = :org_id
                  AND status = 'failed'
                LIMIT 5000
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).all()

    buckets: dict[str, int] = {r: 0 for r in FAILURE_REASONS}
    sample_errors: list[str] = []
    seen: set[str] = set()
    for r in rows:
        reason = _classify_failure(r.error)
        buckets[reason] = buckets.get(reason, 0) + 1
        if r.error and r.error not in seen and len(sample_errors) < 5:
            seen.add(r.error)
            sample_errors.append(r.error)

    return CampaignFailuresReport(
        campaign_id=campaign_id,
        total_failed=sum(buckets.values()),
        buckets=[
            FailureBucket(reason=k, label=_FAILURE_LABELS.get(k, k), count=v)
            for k, v in buckets.items()
        ],
        sample_errors=sample_errors,
    )


# ---------------------------------------------------------------------------
# Org-wide cost estimate
# ---------------------------------------------------------------------------


async def compute_cost(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    region: str = "IN",
    range_key: str = "30d",
) -> CostReport:
    """Estimated Meta cost for outbound WhatsApp traffic in the window.

    Categorisation rules:
      * Campaign messages with a linked WA template → use that
        template's ``category`` (normalised to lowercase).
      * Campaign messages with no template_id → ``utility``
        (legacy free-text broadcasts).
      * Conversation outbound (Step 19 AI + operator replies) →
        ``service`` (the 24-hour session window is free; cost is
        zero in the table).

    Failed sends count toward category totals because Meta still
    charges for failed Marketing template delivery attempts in some
    cases. The estimate caveat label on the UI covers the edge.
    """
    start, end = _resolve_range(range_key)

    campaign_rows = (
        await session.execute(
            text(
                """
                SELECT COALESCE(LOWER(t.category), 'utility') AS category,
                       COUNT(*) AS n
                FROM tbl_campaign_messages cm
                JOIN tbl_campaigns c ON c.id = cm.campaign_id
                -- tasks/template-library Step 11: campaigns.template_id
                -- now points at the central library; join the WA
                -- extension via its message_template_id link to keep
                -- the Meta-side `category` cost classifier working.
                LEFT JOIN tbl_whatsapp_templates t
                       ON t.message_template_id = c.template_id
                WHERE cm.org_id = :org_id
                  AND c.channel = 'whatsapp'
                  AND cm.status IN ('sent','delivered','read','failed')
                  AND cm.created_at >= :start
                  AND cm.created_at <  :end
                GROUP BY 1
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    counts: dict[str, int] = {cat: 0 for cat in cost_estimator.CATEGORIES}
    for r in campaign_rows:
        cat = cost_estimator.normalise_category(r.category)
        counts[cat] = counts.get(cat, 0) + int(r.n or 0)

    # Conversation outbound — service-category traffic (free under the
    # 24h session, but counted so the operator sees volume).
    service_row = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) AS n
                FROM tbl_messages m
                JOIN tbl_conversations c ON c.id = m.conversation_id
                WHERE m.org_id = :org_id
                  AND c.channel = 'whatsapp'
                  AND m.direction = 'out'
                  AND m.is_internal = false
                  AND m.created_at >= :start
                  AND m.created_at <  :end
                  AND NOT EXISTS (
                      SELECT 1 FROM tbl_campaign_messages cm
                      WHERE cm.channel_message_id = m.channel_message_id
                        AND cm.channel_message_id IS NOT NULL
                  )
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).first()
    counts["service"] = counts.get("service", 0) + int((service_row.n if service_row else 0) or 0)

    estimate = cost_estimator.estimate(region=region, counts=counts)
    return CostReport(
        range=range_key,
        region=estimate.region,
        currency=estimate.currency,
        lines=[
            CostLineOut(
                category=line.category,
                count=line.count,
                rate=line.rate,
                currency=line.currency,
                total=line.total,
            )
            for line in estimate.lines
        ],
        total=estimate.total,
        is_estimate=True,
    )


# ---------------------------------------------------------------------------
# Quality timeline
# ---------------------------------------------------------------------------


async def compute_quality_timeline(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "30d",
) -> QualityTimelineReport:
    """Phone-health events + daily send volume.

    Steps 11/12 record every Meta-side phone-quality / messaging-tier
    / restriction change. The dashboard overlays these as event
    annotations on the daily send line so an operator can see "we
    spiked sends on the 14th and got flagged YELLOW on the 16th"."""
    start, end = _resolve_range(range_key)

    event_rows = (
        await session.execute(
            text(
                """
                SELECT occurred_at,
                       event_type::text AS event_type,
                       COALESCE(old_value->>'value', '') AS old_value,
                       COALESCE(new_value->>'value', '') AS new_value
                FROM tbl_whatsapp_phone_health_events
                WHERE org_id = :org_id
                  AND occurred_at >= :start
                  AND occurred_at <  :end
                ORDER BY occurred_at ASC
                LIMIT 200
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    volume_rows = (
        await session.execute(
            text(
                """
                SELECT date_trunc('day', m.created_at AT TIME ZONE 'UTC')
                           AS bucket_start,
                       COUNT(*) AS n
                FROM tbl_messages m
                JOIN tbl_conversations c ON c.id = m.conversation_id
                WHERE m.org_id = :org_id
                  AND c.channel = 'whatsapp'
                  AND m.direction = 'out'
                  AND m.is_internal = false
                  AND m.created_at >= :start
                  AND m.created_at <  :end
                GROUP BY 1
                ORDER BY 1 ASC
                LIMIT 100
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    events: list[QualityEvent] = []
    for r in event_rows:
        ts = r.occurred_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        events.append(
            QualityEvent(
                occurred_at=ts,
                event_type=r.event_type,
                old_value=(r.old_value or None),
                new_value=(r.new_value or None),
            )
        )

    volume: list[QualityVolumePoint] = []
    for r in volume_rows:
        ts = r.bucket_start
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        volume.append(QualityVolumePoint(bucket_start=ts, sent=int(r.n or 0)))

    return QualityTimelineReport(range=range_key, events=events, volume=volume)


# ---------------------------------------------------------------------------
# AI metrics
# ---------------------------------------------------------------------------


async def compute_ai_metrics(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "30d",
) -> AIMetricsReport:
    """AI usage metrics — response rate, escalation rate, completion proxy.

    Definitions:
      * AI replies: outbound messages with ``payload->>'author'='ai'``.
      * Human replies: outbound messages with ``sender_user_id IS NOT NULL``
        and not internal notes.
      * AI response rate: ``ai_replies / (ai_replies + human_replies)``.
      * AI-handled conversations: conversations that had at least one
        AI reply in the window.
      * Escalated conversations: audit-log count of
        ``conversations.ai_escalated`` events.
      * Escalation rate:
        ``escalated_conversations / ai_handled_conversations``.
      * AI-only completion proxy: AI-handled conversations whose
        every outbound row in the window was AI-authored (no human
        intervened).
    """
    start, end = _resolve_range(range_key)

    reply_counts = (
        await session.execute(
            text(
                """
                SELECT
                    SUM(CASE WHEN COALESCE(m.payload->>'author','') = 'ai'
                              THEN 1 ELSE 0 END) AS ai_replies,
                    SUM(CASE WHEN m.sender_user_id IS NOT NULL
                              AND m.is_internal = false
                              THEN 1 ELSE 0 END) AS human_replies
                FROM tbl_messages m
                JOIN tbl_conversations c ON c.id = m.conversation_id
                WHERE m.org_id = :org_id
                  AND c.channel = 'whatsapp'
                  AND m.direction = 'out'
                  AND m.created_at >= :start
                  AND m.created_at <  :end
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).first()

    handled_row = (
        await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT m.conversation_id) AS n
                FROM tbl_messages m
                JOIN tbl_conversations c ON c.id = m.conversation_id
                WHERE m.org_id = :org_id
                  AND c.channel = 'whatsapp'
                  AND m.direction = 'out'
                  AND COALESCE(m.payload->>'author','') = 'ai'
                  AND m.created_at >= :start
                  AND m.created_at <  :end
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).first()

    escalation_rows = (
        await session.execute(
            text(
                """
                SELECT COALESCE(after->>'reason','unknown') AS reason,
                       COUNT(*) AS n
                FROM tbl_audit_logs
                WHERE org_id = :org_id
                  AND action = 'conversations.ai_escalated'
                  AND created_at >= :start
                  AND created_at <  :end
                GROUP BY 1
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    # AI-only completion proxy: conversations where every outbound in
    # the window was AI. NULLIF guards a zero-divide; the query
    # returns 0 when no AI conversations exist.
    ai_only_row = (
        await session.execute(
            text(
                """
                WITH per_conv AS (
                    SELECT m.conversation_id,
                           SUM(CASE WHEN COALESCE(m.payload->>'author','') = 'ai'
                                     THEN 1 ELSE 0 END) AS ai_n,
                           SUM(CASE WHEN m.sender_user_id IS NOT NULL
                                     AND m.is_internal = false
                                     THEN 1 ELSE 0 END) AS human_n
                    FROM tbl_messages m
                    JOIN tbl_conversations c ON c.id = m.conversation_id
                    WHERE m.org_id = :org_id
                      AND c.channel = 'whatsapp'
                      AND m.direction = 'out'
                      AND m.created_at >= :start
                      AND m.created_at <  :end
                    GROUP BY m.conversation_id
                )
                SELECT COUNT(*) AS n
                FROM per_conv
                WHERE ai_n > 0 AND human_n = 0
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).first()

    ai_replies = int((reply_counts.ai_replies if reply_counts else 0) or 0)
    human_replies = int((reply_counts.human_replies if reply_counts else 0) or 0)
    handled = int((handled_row.n if handled_row else 0) or 0)
    ai_only = int((ai_only_row.n if ai_only_row else 0) or 0)

    reasons: dict[str, int] = {}
    total_escalations = 0
    for r in escalation_rows:
        reason_key = str(r.reason or "unknown")
        # Normalise "low_confidence:0.42" into a single bucket so the
        # dashboard counts every escalation reason discretely.
        if reason_key.startswith("low_confidence"):
            reason_key = "low_confidence"
        reasons[reason_key] = reasons.get(reason_key, 0) + int(r.n or 0)
        total_escalations += int(r.n or 0)

    total_out = ai_replies + human_replies
    response_rate = ai_replies / total_out if total_out > 0 else 0.0
    escalation_rate = total_escalations / handled if handled > 0 else 0.0

    return AIMetricsReport(
        range=range_key,
        ai_replies=ai_replies,
        human_replies=human_replies,
        ai_response_rate=round(response_rate, 4),
        ai_handled_conversations=handled,
        escalated_conversations=total_escalations,
        escalation_rate=round(escalation_rate, 4),
        ai_only_completed=ai_only,
        escalation_reasons=reasons,
    )


@dataclass(frozen=True, slots=True)
class AbVariantBreakdown:
    """One side of the A/B comparison (Step 29). All counts are
    integers; ``reply_rate`` / ``read_rate`` / ``click_rate`` are
    0..1 ratios so the SPA can render percentages without doing
    division. Empty samples → 0 across the board."""

    variant: str
    template_id: str | None
    template_name: str | None
    sent: int
    delivered: int
    read: int
    replied: int
    failed: int
    reply_rate: float
    read_rate: float


@dataclass(frozen=True, slots=True)
class AbComparisonReport:
    campaign_id: uuid.UUID
    is_ab_test: bool
    winner_metric: str | None
    winning_variant: str | None
    winner_decided_at: datetime | None
    a: AbVariantBreakdown | None
    b: AbVariantBreakdown | None


async def compute_ab_comparison(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> AbComparisonReport | None:
    """Per-variant side-by-side metrics for the campaign-detail
    Analytics tab (Step 29).

    Returns ``None`` when the campaign doesn't exist; an
    ``AbComparisonReport`` with ``is_ab_test=False`` when the
    campaign is single-template (the UI hides the comparison block
    in that case). For A/B campaigns: one
    ``AbVariantBreakdown`` per side with the same shape so the
    table renders without conditional branches."""
    head = (
        await session.execute(
            text(
                """
                SELECT id, is_ab_test, winner_metric::text AS winner_metric,
                       winning_variant, winner_decided_at,
                       variant_a_template_id, variant_b_template_id
                FROM tbl_campaigns
                WHERE id = :cid AND org_id = :org_id
                """
            ),
            {"cid": campaign_id, "org_id": org_id},
        )
    ).first()
    if head is None:
        return None
    if not bool(head.is_ab_test):
        return AbComparisonReport(
            campaign_id=campaign_id,
            is_ab_test=False,
            winner_metric=None,
            winning_variant=None,
            winner_decided_at=None,
            a=None,
            b=None,
        )

    async def _variant(letter: str, tpl_id) -> AbVariantBreakdown:
        # Per-variant funnel counts using the same status taxonomy
        # as `compute_campaign_funnel`. Reply count uses the same
        # CTE shape as the standalone funnel — minor duplication
        # for clarity vs sharing a helper with subtle bool params.
        counts = (
            await session.execute(
                text(
                    """
                    SELECT
                      COUNT(*) AS sent_q,
                      SUM(CASE WHEN status IN ('sent','delivered','read')
                               THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN status IN ('delivered','read')
                               THEN 1 ELSE 0 END) AS delivered,
                      SUM(CASE WHEN status = 'read' THEN 1 ELSE 0 END) AS read,
                      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                    FROM tbl_campaign_messages
                    WHERE campaign_id = :cid AND variant = :v
                    """
                ),
                {"cid": campaign_id, "v": letter},
            )
        ).first()
        replied_row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT cm.contact_id) AS replied
                    FROM tbl_campaign_messages cm
                    JOIN tbl_conversations c ON c.contact_id = cm.contact_id
                    JOIN tbl_messages m
                         ON m.conversation_id = c.id
                        AND m.direction = 'in'
                    WHERE cm.campaign_id = :cid
                      AND cm.variant = :v
                      AND cm.sent_at IS NOT NULL
                      AND m.created_at >  cm.sent_at
                      AND m.created_at <= cm.sent_at + INTERVAL '7 days'
                    """
                ),
                {"cid": campaign_id, "v": letter},
            )
        ).first()
        tpl_name = None
        if tpl_id is not None:
            # tasks/template-library Step 11: `tpl_id` (= campaign's
            # template_id column) now points at the central library.
            tpl_row = (
                await session.execute(
                    text("SELECT name FROM tbl_message_templates WHERE id = :tid"),
                    {"tid": tpl_id},
                )
            ).first()
            tpl_name = tpl_row.name if tpl_row else None
        sent = int(counts.sent or 0) if counts else 0
        delivered = int(counts.delivered or 0) if counts else 0
        read_n = int(counts.read or 0) if counts else 0
        replied = int((replied_row.replied if replied_row else 0) or 0)
        failed = int(counts.failed or 0) if counts else 0
        return AbVariantBreakdown(
            variant=letter,
            template_id=str(tpl_id) if tpl_id else None,
            template_name=tpl_name,
            sent=sent,
            delivered=delivered,
            read=read_n,
            replied=replied,
            failed=failed,
            reply_rate=round(replied / delivered, 4) if delivered else 0.0,
            read_rate=round(read_n / delivered, 4) if delivered else 0.0,
        )

    a = await _variant("A", head.variant_a_template_id)
    b = await _variant("B", head.variant_b_template_id)
    decided_at = head.winner_decided_at
    if decided_at is not None and decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=UTC)
    return AbComparisonReport(
        campaign_id=campaign_id,
        is_ab_test=True,
        winner_metric=head.winner_metric,
        winning_variant=head.winning_variant,
        winner_decided_at=decided_at,
        a=a,
        b=b,
    )


__all__ = [
    "FAILURE_REASONS",
    "FunnelStage",
    "CampaignFunnelReport",
    "FailureBucket",
    "CampaignFailuresReport",
    "CostLineOut",
    "CostReport",
    "QualityEvent",
    "QualityVolumePoint",
    "QualityTimelineReport",
    "AIMetricsReport",
    "AbVariantBreakdown",
    "AbComparisonReport",
    "compute_campaign_funnel",
    "compute_campaign_failures",
    "compute_cost",
    "compute_quality_timeline",
    "compute_ai_metrics",
    "compute_ab_comparison",
    "_classify_failure",
]
