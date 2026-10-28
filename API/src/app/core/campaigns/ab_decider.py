"""Campaign A/B winner decision
(whatsapp-platform-upgrade Step 29).

Single public entry point — :func:`decide_winner` — invoked by the
Celery task ``run_ab_decision`` ``winner_holdback_hours`` after the
A/B chunks are dispatched. Computes the chosen ``winner_metric``
per variant + writes ``winning_variant`` + ``winner_decided_at``
back to the campaign row.

Per-variant aggregation
-----------------------

Three metrics, all expressed as a 0..1 ratio so the comparison is
apples-to-apples regardless of variant volume:

  * ``reply_rate``  — distinct customers who messaged back within
    the hold-back window / messages delivered.
  * ``read_rate``   — read receipts / delivered count.
  * ``click_rate``  — Meta-flagged "clicked" outbound (button or CTA
    URL replies) / delivered count. Falls back to reply_rate when
    Meta hasn't flagged any clicks for this WABA tier — better a
    soft fallback than a silent zero.

Tie-break: variant A wins on equal metrics. Operators inspecting
"A == B" decisions can see the audit log entry that captures both
ratios + the sample sizes so an SRE can sanity-check.

Edge cases
----------

  * Either variant 0 sends → fall back to the other. If both 0
    (unlikely; dispatch crashed mid-run), no winner — caller logs
    + leaves the campaign in its current state.
  * Winner already decided → no-op + log. Lets the task be
    re-queued safely after a Celery worker restart.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.campaigns.models import Campaign

logger = logging.getLogger(__name__)


Variant = Literal["A", "B"]
WinnerMetric = Literal["reply_rate", "read_rate", "click_rate"]


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    """One side of the comparison. ``samples`` is the denominator
    (messages delivered); ``numerator`` is the metric-specific
    count (replies / reads / clicks). ``rate`` is the divided
    value, capped at 1.0 to be safe against double-counts."""

    variant: Variant
    samples: int
    numerator: int
    rate: float


@dataclass(frozen=True, slots=True)
class WinnerDecision:
    winning_variant: Variant | None
    metric: WinnerMetric
    a: VariantMetrics
    b: VariantMetrics
    reason: str


async def _per_variant_metrics(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    variant: Variant,
    metric: WinnerMetric,
) -> VariantMetrics:
    """Compute ``(samples, numerator, rate)`` for one variant.

    Uses raw SQL because the join shape touches three tables
    (``tbl_campaign_messages`` + ``tbl_conversations`` +
    ``tbl_messages`` for replies) and SQLAlchemy's query builder
    would obscure the intent here. RLS still applies via the
    standard ``app.org_id`` session setting."""
    if metric == "read_rate":
        stmt = sql_text(
            """
            SELECT
              SUM(CASE WHEN status IN ('delivered','read') THEN 1 ELSE 0 END) AS samples,
              SUM(CASE WHEN status = 'read' THEN 1 ELSE 0 END) AS numerator
            FROM tbl_campaign_messages
            WHERE campaign_id = :cid AND variant = :v
            """
        )
        row = (await session.execute(stmt, {"cid": campaign_id, "v": variant})).first()
        samples = int((row.samples if row else 0) or 0)
        numerator = int((row.numerator if row else 0) or 0)
    elif metric == "click_rate":
        # Clicks are inferred from inbound interactive replies tied
        # to the campaign message — Meta's `button_reply` / `list_reply`
        # events. We use the existing reply join + filter on
        # interactive payload presence.
        stmt = sql_text(
            """
            WITH delivered AS (
              SELECT id, contact_id, sent_at
              FROM tbl_campaign_messages
              WHERE campaign_id = :cid AND variant = :v
                AND status IN ('delivered','read')
            )
            SELECT
              (SELECT COUNT(*) FROM delivered) AS samples,
              COUNT(DISTINCT d.contact_id) AS numerator
            FROM delivered d
            JOIN tbl_conversations c ON c.contact_id = d.contact_id
            JOIN tbl_messages m
              ON m.conversation_id = c.id
             AND m.direction = 'in'
             AND m.created_at > d.sent_at
             AND m.created_at < d.sent_at + INTERVAL '7 days'
             AND (m.payload ? 'button_reply' OR m.payload ? 'list_reply')
            """
        )
        row = (await session.execute(stmt, {"cid": campaign_id, "v": variant})).first()
        samples = int((row.samples if row else 0) or 0)
        numerator = int((row.numerator if row else 0) or 0)
        if samples > 0 and numerator == 0:
            # Soft fallback: if Meta hasn't flagged any interactive
            # clicks for this WABA tier (most non-enterprise WABAs
            # never see them) fall back to plain replies so the
            # winner isn't always "0 vs 0".
            logger.info(
                "click_rate: no interactive clicks found for variant %s — "
                "falling back to reply_rate",
                variant,
            )
            return await _per_variant_metrics(
                session,
                campaign_id=campaign_id,
                variant=variant,
                metric="reply_rate",
            )
    else:  # reply_rate
        stmt = sql_text(
            """
            WITH delivered AS (
              SELECT id, contact_id, sent_at
              FROM tbl_campaign_messages
              WHERE campaign_id = :cid AND variant = :v
                AND status IN ('delivered','read')
            )
            SELECT
              (SELECT COUNT(*) FROM delivered) AS samples,
              COUNT(DISTINCT d.contact_id) AS numerator
            FROM delivered d
            JOIN tbl_conversations c ON c.contact_id = d.contact_id
            JOIN tbl_messages m
              ON m.conversation_id = c.id
             AND m.direction = 'in'
             AND m.created_at > d.sent_at
             AND m.created_at < d.sent_at + INTERVAL '7 days'
            """
        )
        row = (await session.execute(stmt, {"cid": campaign_id, "v": variant})).first()
        samples = int((row.samples if row else 0) or 0)
        numerator = int((row.numerator if row else 0) or 0)

    rate = (numerator / samples) if samples > 0 else 0.0
    return VariantMetrics(
        variant=variant,
        samples=samples,
        numerator=numerator,
        rate=min(1.0, rate),
    )


def _pick_winner(a: VariantMetrics, b: VariantMetrics) -> tuple[Variant | None, str]:
    """Return ``(winner, reason)`` or ``(None, reason)`` when no
    winner can be picked. Tie-break: A wins on equal rates."""
    if a.samples == 0 and b.samples == 0:
        return None, "no samples on either variant"
    if a.samples == 0:
        return "B", "variant A had no samples"
    if b.samples == 0:
        return "A", "variant B had no samples"
    if a.rate > b.rate:
        return "A", f"A rate {a.rate:.4f} > B rate {b.rate:.4f}"
    if b.rate > a.rate:
        return "B", f"B rate {b.rate:.4f} > A rate {a.rate:.4f}"
    return "A", "tie-break: A wins on equal rate"


async def decide_winner(session: AsyncSession, *, campaign_id: uuid.UUID) -> WinnerDecision | None:
    """Run the winner decision for ``campaign_id``.

    Returns the :class:`WinnerDecision` (winner + per-variant
    breakdown) on success, ``None`` when the campaign isn't an A/B
    test, the winner was already decided, or the campaign doesn't
    exist. Persists ``winning_variant`` + ``winner_decided_at`` and
    emits a ``campaigns.ab_winner_decided`` audit event."""
    campaign = (
        await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    ).scalar_one_or_none()
    if campaign is None:
        return None
    if not campaign.is_ab_test:
        return None
    if campaign.winning_variant is not None:
        logger.info(
            "decide_winner: campaign %s already has winner %s — no-op",
            campaign_id,
            campaign.winning_variant,
        )
        return None

    metric: WinnerMetric = (
        campaign.winner_metric  # type: ignore[assignment]
        or "reply_rate"
    )
    a = await _per_variant_metrics(
        session,
        campaign_id=campaign_id,
        variant="A",
        metric=metric,
    )
    b = await _per_variant_metrics(
        session,
        campaign_id=campaign_id,
        variant="B",
        metric=metric,
    )
    winner, reason = _pick_winner(a, b)

    decision = WinnerDecision(
        winning_variant=winner,
        metric=metric,
        a=a,
        b=b,
        reason=reason,
    )

    if winner is not None:
        campaign.winning_variant = winner
        campaign.winner_decided_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(campaign)
        await audit.log(
            "campaigns.ab_winner_decided",
            entity_type="campaign",
            entity_id=campaign_id,
            after={
                "winning_variant": winner,
                "metric": metric,
                "reason": reason,
                "a": {
                    "samples": a.samples,
                    "numerator": a.numerator,
                    "rate": a.rate,
                },
                "b": {
                    "samples": b.samples,
                    "numerator": b.numerator,
                    "rate": b.rate,
                },
            },
        )
    else:
        logger.warning(
            "decide_winner: no winner picked for campaign %s — %s",
            campaign_id,
            reason,
        )

    return decision


__all__ = [
    "VariantMetrics",
    "WinnerDecision",
    "_pick_winner",
    "decide_winner",
]
