# Step 21 — Campaign analytics + funnel + cost dashboard + quality timeline

**Goal:** Per-campaign rollup (funnel + failure breakdown + cost), org-wide WhatsApp cost dashboard (Meta conversation-pricing categories), and quality-timeline chart correlating quality + tier + send volume.
**Status:** COMPLETED
**Depends on:** Step 12 (quality history events), Step 20 (analytics widget library reuse).

---

## Scope

In-scope:
- Per-campaign aggregation:
  - Targeted / sent / delivered / read / replied / clicked / failed (with reason breakdown)
  - Time-to-delivery distribution
  - Conversion: deals/leads created within 7 days of receipt (existing tables)
- Cost estimation:
  - Map outbound to Meta conversation-pricing categories (Marketing / Utility / Authentication / Service)
  - Multiply by India / UAE / US rates (hardcoded, env-override)
  - Per-campaign + per-month total
- Endpoints:
  - `GET /api/v1/reports/campaigns/{id}/funnel`
  - `GET /api/v1/reports/campaigns/{id}/failures`
  - `GET /api/v1/reports/whatsapp/cost?range=...`
  - `GET /api/v1/reports/whatsapp/quality-timeline?range=...`
- Frontend:
  - Campaign detail → new "Analytics" tab with funnel chart + failure table + recipient drill-down.
  - Reporting → "Cost this month" widget with per-category breakdown.
  - Reporting → "Quality timeline" chart with event annotations from Step 12.
- AI-specific metrics (added because Step 19 wires AI):
  - AI response rate, escalation rate, AI-only completion proxy

Out of scope:
- A/B testing analytics — Step 29.
- Sub-org / per-store rollups — wait for multi-number (Step 27).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/reporting/campaign_analytics.py` | **NEW** |
| `API/src/app/core/reporting/cost_estimator.py` | **NEW** |
| `API/src/app/core/reporting/router.py` | New endpoints |
| `APP/.../campaigns/detail/analytics-tab.component.ts` | **NEW** |
| `APP/.../campaigns/detail/funnel-chart.component.ts` | **NEW** |
| `APP/.../campaigns/detail/failures-table.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/cost-widget.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/quality-timeline.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/ai-metrics-widget.component.ts` | **NEW** |
| `API/tests/reporting/test_campaign_analytics.py` | **NEW** |

**~10 files. ~700 lines.**

## Plan

1. Aggregation SQL joins `tbl_campaigns` + `tbl_campaign_messages` + `tbl_conversation_messages`.
2. Failure reason taxonomy: rate_limited / invalid_number / opted_out / template_paused / quality_restricted / other.
3. Conversion query: lookup deals/leads with `source_campaign_id = ?` created within 7d of message receipt.
4. Cost rate table hardcoded for IN / AE / US with env override `WHATSAPP_COST_RATES_OVERRIDE`.
5. Quality timeline pulls from Step 12's `tbl_whatsapp_phone_health_events` + correlates with daily send volume.
6. Tests: funnel math, cost calculation per region, failure grouping, conversion lookup.

## DB changes / migrations

Optional `tbl_orgs.region` / `currency` if not present. Defer until needed.

## Tests

10 pytest + 3 Jest.

## Smoke

```
1. Send a campaign of 100 messages with marketing template.
2. Campaign detail → Analytics tab → funnel: 100 → 95 sent → 90 delivered → 60 read → 12 replied → 3 converted.
3. Failure table breaks down 5 failures by reason.
4. Cost widget: "Estimated cost this month: ₹X" with per-category split.
5. Quality timeline overlays drops with send-volume spikes.
6. AI metrics widget: 40% AI-handled, 10% escalated.
```

## Risks

- Cost is estimate, not invoice — label clearly.
- Conversion attribution: 7-day window is arbitrary; document + make configurable later if asked.

## Self-check (10 rules)

All `core/reporting/`. ✓. Service-level org_id. ✓. No custom-field changes. ✓. Static widgets. ✓ N/A. Reporting descriptor. ✓. Existing `whatsapp.analytics.read`. ✓. pack.yaml untouched. ✓. 10 files / ~700 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 21 — Campaign analytics + cost + quality timeline
Files: 10
Verify: funnel + failure breakdown + cost estimate + timeline + AI metrics.
Tests: 10 pytest + 3 Jest.
Phase 7 (Analytics) complete. Next: Step 22 — opt-in capture.
Awaiting "proceed".
```
