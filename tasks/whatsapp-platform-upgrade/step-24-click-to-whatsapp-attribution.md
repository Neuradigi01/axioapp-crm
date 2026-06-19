# Step 24 — Click-to-WhatsApp ad attribution

**Goal:** Capture Meta Ad referral payload on inbound WhatsApp messages → attribute conversations to their source ad / campaign. Surface attribution chips in conversations + ad ROI dashboard in Reporting.
**Status:** Pending
**Depends on:** Existing Meta Ads OAuth wiring + Phase 1 closed.

---

## Scope

In-scope:
- Inbound webhook: capture Meta's referral object on first message (contains `source_type`, `source_id` ad id, `source_url`, `body` prefilled text, `headline`, etc.).
- Schema additions to `tbl_conversations`:
  - `acquisition_source` ENUM (`organic` / `ad` / `qr` / `wa_me` / `form`)
  - `acquisition_campaign_id`, `acquisition_ad_id`, `acquisition_landing_url`, `acquisition_referral_payload JSONB`
- For ad source: lookup Meta Ads campaign via existing OAuth tokens; persist campaign name + ad creative ref.
- Endpoints:
  - `GET /api/v1/conversations/{id}/attribution` — current state
  - `GET /api/v1/reports/whatsapp/ad-attribution?range=...` — aggregated per-campaign conversations + deals + revenue
- Frontend:
  - Conversation header attribution chip ("From: Meta Ad — Summer Sale") with deeplink to Meta Ads Manager.
  - Reporting → "Ad ROI" widget (extends Step 21 reporting page).

Out of scope:
- QR + wa.me attribution — Step 26.
- Multi-touch attribution — single-touch (last-source) only.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | Add attribution columns |
| `API/alembic/versions/<ts>_conversation_attribution.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Parse referral payload on first inbound |
| `API/src/app/core/integrations/meta/ads_lookup.py` | **NEW** ad-id → campaign-name resolver |
| `API/src/app/core/conversations/router.py` | New attribution endpoint |
| `API/src/app/core/reporting/ad_attribution.py` | **NEW** aggregation |
| `API/src/app/core/reporting/router.py` | Extend |
| `APP/.../conversations/header/attribution-chip.component.ts` | **NEW** |
| `APP/.../reporting/whatsapp/ad-roi-widget.component.ts` | **NEW** |
| `API/tests/integrations/test_attribution.py` | **NEW** |

**~10 files. ~500 lines.**

## Plan

1. Migration: 5 columns nullable.
2. Webhook handler: if `referral` block present on first inbound, populate columns + call Meta Ads lookup.
3. Ads lookup: cache campaign name per ad-id for 24h (Redis).
4. Reporting query joins conversations → deals/leads with `source_conversation_id` (existing FK?).
5. Frontend chip + deeplink construction.
6. Tests: referral parse, lookup success/fail, aggregation math.

## DB changes / migrations

5 columns on `tbl_conversations`.

## Tests

6 pytest + 2 Jest.

## Smoke

```
1. Click a Meta Ad CTA "Send WhatsApp message" → opens WhatsApp with prefilled text.
2. Send the prefilled text.
3. Core CRM creates conversation with acquisition_source=ad + campaign name.
4. Conversation header shows chip "From: Meta Ad — Summer Sale".
5. Click chip → deeplinks to Meta Ads Manager.
6. Reporting → Ad ROI widget shows attributed conversations / deals.
7. Organic (non-ad) inbound: no chip, no attribution columns.
```

## Risks

- Referral payload occasionally dropped by Meta — document caveat: best-effort attribution.
- Ad lookup needs cached Meta Ads token (existing).

## Self-check (10 rules)

`core/conversations/` + `core/integrations/meta/` + `core/reporting/`. ✓. org_id preserved. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. No registry change. ✓. Existing perms. ✓. pack.yaml untouched. ✓. 10 files / ~500 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 24 — Click-to-WhatsApp attribution
Files: 10
Verify: referral capture + campaign resolution + chip + Ad ROI widget.
Tests: 6 pytest + 2 Jest.
Next: Step 25 — WhatsApp Flows.
Awaiting "proceed".
```
