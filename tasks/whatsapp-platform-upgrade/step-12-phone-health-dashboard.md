# Step 12 — Phone health & quality dashboard

**Goal:** Surface WhatsApp phone-number health (quality rating, messaging limit tier, restrictions, throughput, verified name status) on the Integrations page + a dashboard widget. Customer reacts to drops before Meta suspends.
**Status:** Pending
**Depends on:** Phase 1 webhook subscriptions (`phone_number_quality_update` event subscribed in Step 1).

---

## Scope

In-scope:
- Webhook handler for `phone_number_quality_update` events → write to new `tbl_whatsapp_phone_health_events` (org_id, phone_id, event_type, old_value, new_value, occurred_at).
- Periodic hourly refresh (Celery beat) calling `GET /{phone_id}?fields=quality_rating,messaging_limit_tier,name_status,code_verification_status,throughput,is_official_business_account`. Cache in extended `WhatsAppCapacity` row.
- Endpoint `GET /api/v1/integrations/whatsapp/phone-health` → current state + 30-day event timeline.
- Frontend card on Integrations page WhatsApp section:
  - Quality badge (🟢 / 🟡 / 🔴) with tooltip explaining each level + recovery suggestions
  - Messaging limit tier badge (1K / 10K / 100K / Unlimited per 24h) + 24-hr usage progress bar
  - Restrictions banner (red, if Meta has restricted) with reason + estimated lift date
  - Verified name approval state
  - Throughput
  - Quality timeline chart (last 30 days) with click-to-zoom on change points
  - Recovery checklist (visible when Yellow/Red) — actionable items
- Dashboard widget "WhatsApp health" — quality + tier at a glance, click → integrations page.

Out of scope:
- Multi-number per org — Step 27 (health here is per single number until then).
- Automated alerts on quality drop — Phase 7 analytics.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/health_service.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | Add `tbl_whatsapp_phone_health_events`; extend WhatsAppCapacity |
| `API/alembic/versions/<ts>_phone_health_events.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Handle `phone_number_quality_update` event |
| `API/src/app/core/integrations/whatsapp/health_tasks.py` | **NEW** Celery hourly refresh task |
| `API/src/app/core/integrations/whatsapp/router.py` | New `/phone-health` endpoint |
| `APP/.../whatsapp/phone-health/phone-health-card.component.ts` | **NEW** |
| `APP/.../whatsapp/phone-health/quality-timeline.component.ts` | **NEW** |
| `APP/.../whatsapp/phone-health/recovery-checklist.component.ts` | **NEW** |
| `APP/.../settings/integrations/whatsapp-card.component.ts` | Embed phone-health-card |
| `APP/.../dashboard/widgets/whatsapp-health-widget.component.ts` | **NEW** dashboard widget |
| `API/tests/integrations/test_whatsapp_phone_health.py` | **NEW** |

**~12 files. ~700 lines.**

## Plan

1. Migration creates events table; extend Capacity with `name_status`, `throughput`, `restrictions JSONB`.
2. Service: refresh fetches all fields in one call; computes deltas; writes events.
3. Webhook handler: idempotent (Meta retries possible); event_type is enum (`quality_change`, `tier_change`, `restriction_added`, `restriction_lifted`).
4. Celery beat schedule entry: hourly task per org with active integration.
5. Frontend card subscribes to status via existing polling pattern.
6. Recovery checklist keys: high-block-rate, marketing-template-paused, send-volume-spike, template-rejection-rate — show conditionally based on event reasons.
7. Tests: webhook idempotency, timeline ordering, tier-bump UX (green toast), restriction banner appearance.

## DB changes / migrations

```sql
CREATE TABLE tbl_whatsapp_phone_health_events (
  id UUID PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES tbl_organizations(id),
  phone_id VARCHAR(64) NOT NULL,
  event_type whatsapp_phone_health_event_type_enum NOT NULL,
  old_value JSONB,
  new_value JSONB,
  occurred_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_phone_health_events_org_phone ON tbl_whatsapp_phone_health_events(org_id, phone_id, occurred_at DESC);
ALTER TABLE tbl_whatsapp_capacity ADD COLUMN name_status VARCHAR(32), ADD COLUMN throughput INT, ADD COLUMN restrictions JSONB;
```
RLS enabled on events table.

## Tests

7 pytest cases.

## Smoke

```
1. Integrations page shows WhatsApp card with Phone health strip: 🟢 Green / Tier 1K / 24-hr usage 12/1000.
2. Simulate quality drop via webhook fixture → status flips to 🟡 within seconds; banner appears with reason; recovery checklist visible.
3. Quality timeline chart shows 30-day series with drop annotated.
4. Tier bump simulation (1K → 10K) → celebratory toast.
5. Restriction event → red banner with estimated lift date.
6. Dashboard widget shows current quality + tier.
7. Hourly Celery refresh runs and writes a no-change event (idempotent).
```

## Risks

- Quality rating drop reasons are vague from Meta — recovery suggestions stay generic, no false specifics.
- Hourly refresh × many orgs = API call volume; batch or stagger.
- Webhook out-of-order delivery: use `occurred_at` from payload, not `recorded_at`.

## Self-check (10 rules)

All `core/integrations/whatsapp/` + dashboard widget. ✓ Rule 1. New table org_id + RLS. ✓ Rule 2. No custom-field changes. ✓ Rule 3. Static cards. ✓ Rule 4 N/A. No new permission (uses `whatsapp.read`). ✓ Rule 6. pack.yaml untouched. ✓. 12 files / ~700 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 12 — Phone health dashboard
Files: 12
Verify: quality / tier / restriction surface; timeline; recovery checklist; hourly refresh; dashboard widget.
Tests: 7 pytest cases.
Phase 4 (Business profile + health) complete. Next: Step 13 — internal notes.
Awaiting "proceed".
```
