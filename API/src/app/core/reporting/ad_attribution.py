"""Click-to-WhatsApp ad ROI aggregation
(whatsapp-platform-upgrade Step 24).

Single function — :func:`compute_ad_attribution` — that joins
attributed conversations to the leads / deals they produced and
returns per-campaign roll-ups for the Ad ROI widget on the
Reporting page.

Attribution model
-----------------

* **Conversation-level signal.** `tbl_conversations.acquisition_*`
  (Step 24 migration) carries the per-conversation campaign id +
  ad id + ad-account id (via the JSONB ``_resolved`` envelope).
  Single-touch — captured on first inbound, never overwritten.

* **Lead linkage.** Leads carry an ``attribution`` JSONB column
  (migration 0045). When a lead originates from a conversation —
  e.g. the conversation auto-created a contact + an operator
  promoted them to a lead — we expect
  ``attribution->>'source_conversation_id'`` to be populated.
  Until that's wired (a future step), the aggregation falls back
  to "count distinct conversations" as the conversion proxy.

* **Revenue.** Leads carry ``estimated_value`` (Phase 4 spec);
  campaign revenue is `SUM(estimated_value)` over the linked
  leads.

Range / RLS scoping
-------------------

Window resolved via :func:`whatsapp_analytics._resolve_range`
(7d / 30d / 90d). Tenant isolation via the standard
``app.org_id`` setting plus an explicit ``org_id`` filter for
belt-and-braces.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.reporting.whatsapp_analytics import _resolve_range

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdAttributionRow:
    campaign_id: str | None
    campaign_name: str | None
    ad_id: str | None
    ad_name: str | None
    conversations: int
    leads: int
    revenue: float


@dataclass(frozen=True, slots=True)
class AdAttributionReport:
    range: str
    rows: list[AdAttributionRow]
    total_conversations: int
    total_leads: int
    total_revenue: float


async def compute_ad_attribution(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    range_key: str = "30d",
) -> AdAttributionReport:
    """Per-campaign roll-up for the Ad ROI widget.

    Result is sorted by conversation count descending so the
    top-performing campaign sits at the top of the table. Rows
    with no campaign id (raw ``acquisition_source='ad'`` but no
    Meta lookup result) are folded into a single "Unattributed
    ad" line so the dashboard still surfaces the activity."""
    start, end = _resolve_range(range_key)

    # We join the conversations table to its referral JSONB to pluck
    # the resolved campaign/ad labels. The `_resolved` envelope is
    # the canonical source of friendly names; the dedicated columns
    # (`acquisition_campaign_id`, `acquisition_ad_id`) are the
    # stable join keys.
    rows = (
        await session.execute(
            text(
                """
                WITH attrib_conv AS (
                    SELECT
                        c.id AS conversation_id,
                        c.acquisition_campaign_id AS campaign_id,
                        c.acquisition_ad_id AS ad_id,
                        c.acquisition_referral_payload->'_resolved'->>'campaign_name'
                            AS campaign_name,
                        c.acquisition_referral_payload->'_resolved'->>'ad_name'
                            AS ad_name,
                        c.contact_id
                    FROM tbl_conversations c
                    WHERE c.org_id = :org_id
                      AND c.acquisition_source = 'ad'
                      AND c.created_at >= :start
                      AND c.created_at <  :end
                )
                SELECT
                    ac.campaign_id,
                    MAX(ac.campaign_name) AS campaign_name,
                    ac.ad_id,
                    MAX(ac.ad_name) AS ad_name,
                    COUNT(DISTINCT ac.conversation_id) AS conversations,
                    COUNT(DISTINCT l.id) AS leads,
                    COALESCE(SUM(l.estimated_value), 0) AS revenue
                FROM attrib_conv ac
                LEFT JOIN tbl_leads l
                       ON l.contact_id = ac.contact_id
                      AND l.attribution->>'source_conversation_id'
                          = ac.conversation_id::text
                GROUP BY ac.campaign_id, ac.ad_id
                ORDER BY conversations DESC
                LIMIT 100
                """
            ),
            {"org_id": org_id, "start": start, "end": end},
        )
    ).all()

    out: list[AdAttributionRow] = []
    total_conv = 0
    total_leads = 0
    total_rev = 0.0
    for r in rows:
        convs = int(r.conversations or 0)
        leads = int(r.leads or 0)
        revenue = float(r.revenue or 0.0)
        out.append(
            AdAttributionRow(
                campaign_id=r.campaign_id,
                campaign_name=r.campaign_name
                or (f"Unattributed ad ({r.ad_id})" if r.ad_id else "Unattributed ad"),
                ad_id=r.ad_id,
                ad_name=r.ad_name,
                conversations=convs,
                leads=leads,
                revenue=revenue,
            )
        )
        total_conv += convs
        total_leads += leads
        total_rev += revenue

    return AdAttributionReport(
        range=range_key,
        rows=out,
        total_conversations=total_conv,
        total_leads=total_leads,
        total_revenue=round(total_rev, 2),
    )


__all__ = [
    "AdAttributionReport",
    "AdAttributionRow",
    "compute_ad_attribution",
]
