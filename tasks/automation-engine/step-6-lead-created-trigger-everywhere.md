# Step 6 — lead.created event from everywhere + Lead Confirmation trigger seed

**Goal:** Publish `lead.created` from EVERY lead-capture source uniformly. Seed a default "Lead Confirmation" trigger so any new lead gets an automatic confirmation message (email + optional WhatsApp). This is the second of the two specific manager asks ("mail to lead automatically when the lead id submitted via anywhere") landed end-to-end.
**Status:** Pending
**Depends on:** Steps 1-5 (engine + Welcome seed pattern).

---

## Scope

In-scope:
- `core/events/event_catalog.py`: add `lead.created` shape `{lead_id, org_id, contact_id, source, attribution, created_at, contact_snapshot, lead_snapshot}`.
- Publish `lead.created` from **every** existing lead-capture site:
  - Manual entry — `core/contacts/router.py` (when a contact is created with `is_lead=true` flag, or via the dedicated leads endpoint).
  - Bulk CSV import — `core/lead_capture/import/service.py` (one event per row imported).
  - Google Ads webhook — `core/integrations/google/webhook.py` (existing publisher, if any — extend or add).
  - Meta Ads webhook (FB + IG Lead Ads) — `core/integrations/meta/webhook.py`.
  - Embedded JS form widget — `core/lead_capture/forms/service.py`.
  - WhatsApp inbound first-message → new contact — `core/conversations/service.py` (`_find_or_create_conversation` path).
  - Walk-in registration — `core/walk_ins/service.py` (if exists; skip otherwise — module may not be live yet).
  - API direct contact creation — same `core/contacts/router.py` path.
- Each publish call uses a deterministic event_id of `f"lead_created:{lead_id}"` to absorb duplicates.
- `core/automation/seeds.py` (extension):
  - `seed_lead_confirmation_template(org_id, db)` — default email template "Lead Confirmation". Body uses `{{contact.first_name}}`, `{{org.name}}`. Idempotent.
  - `seed_lead_confirmation_trigger(org_id, template_id, db)` — `lead.created → email → template_id`, `delay_seconds=0`, `recipient_resolver=contact.email`. Idempotent.
- `core/tenants/service.py`: call new seeders on org creation.
- Backfill migration `<ts>_seed_lead_confirmation_existing_orgs.py`: backfill for existing orgs.
- Pin test `test_lead_created_publish_coverage.py` — grep-style check that every lead-creation site is wired (count the publish calls; if a new source is added later without publishing, this test fails).

Out of scope:
- WhatsApp variant of the confirmation message — operator can clone the trigger and switch channel after this lands. Seeded default is email only at v1.
- Lead source-specific overrides ("if source=meta_ads use template X, else Y") — operator builds via conditions on the trigger row.
- Walk-in source if the walk-ins module isn't built yet — skipped gracefully + documented.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | edit — register `lead.created` |
| `API/src/app/core/contacts/router.py` | edit — publish on lead creation |
| `API/src/app/core/lead_capture/import/service.py` | edit — publish per imported row |
| `API/src/app/core/lead_capture/forms/service.py` | edit — publish on widget submission |
| `API/src/app/core/integrations/google/webhook.py` | edit — publish on Google Ads lead delivery |
| `API/src/app/core/integrations/meta/webhook.py` | edit — publish on Meta Ads lead delivery |
| `API/src/app/core/conversations/service.py` | edit — publish on first-time WhatsApp inbound creating a new contact |
| `API/src/app/core/automation/seeds.py` | edit — add lead-confirmation seeders |
| `API/src/app/core/tenants/service.py` | edit — call new seeders |
| `API/alembic/versions/<ts>_seed_lead_confirmation_existing_orgs.py` | **NEW** |
| `API/tests/automation/test_lead_created.py` | **NEW** |
| `API/tests/automation/test_lead_created_publish_coverage.py` | **NEW** — pin test |

**~12 files. ~600 lines.**

## Plan

1. Catalog entry first.
2. Add publish calls to every source — keep them tiny (`events.publish("lead.created", {...}, org_id=...)`) and AFTER the lead row commits.
3. Seeders + tenants service update + backfill.
4. Tests: one per source publishes; the seeded trigger fires for any source.
5. Pin test that fails CI if a future code change removes a publish call.

## DB changes / migrations

One backfill migration only — no schema change.

## Tests

12 pytest cases:
- `test_manual_lead_publishes_event`
- `test_bulk_import_publishes_event_per_row`
- `test_widget_submission_publishes_event`
- `test_google_ads_webhook_publishes_event`
- `test_meta_ads_webhook_publishes_event`
- `test_whatsapp_first_inbound_publishes_event_when_new_contact`
- `test_seeded_trigger_fires_for_any_source`
- `test_lead_confirmation_template_renders_correctly`
- `test_seeders_idempotent`
- `test_backfill_existing_orgs_creates_template_and_trigger`
- `test_publish_coverage_pin` — counts publish call sites
- `test_disabling_seeded_trigger_skips_for_subsequent_lead_creations`

## Smoke

```
1. Submit a lead via the embedded form widget on a public test page.
2. Audit log: lead.created event.
3. tbl_automation_runs: one row, status=queued → sent.
4. The lead's email inbox: confirmation arrived.
5. Trigger a Google Ads lead via the webhook test endpoint.
6. tbl_automation_runs: another run row.
7. Open /api/v1/automations/triggers as Owner → "Lead Confirmation" trigger visible.
8. PATCH conditions: {"field": "source", "op": "eq", "value": "meta_ads"} → re-trigger via manual entry → no run fires (source mismatch).
9. Re-publish via the Meta webhook → run fires.
```

## Risks

- Publish-call discipline: every NEW lead source added in the future must also publish. Pin test catches grep-omission; comments at each publish site document the contract.
- Walk-in source not yet built — skip cleanly. Add the publish call when the walk-in module lands.
- Bulk import on a 10,000-row CSV publishes 10,000 events → 10,000 Celery tasks → 10,000 outbound emails. **At v1 this is acceptable** because the seeded trigger is disabled by default for `source=bulk_import` until the operator confirms intent. Conditions: `{"field": "source", "op": "ne", "value": "bulk_import"}` baked into the seed.

## Self-check (10 rules)

Wide cross-module touch (~7 publish sites), all in `core/`. ✓ org_id propagated. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already registered. ✓ pack.yaml untouched. ✓ 12 files / ~600 lines — at Rule 8 upper bound; justified by the "via anywhere" requirement that's intrinsically cross-module. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 6 — lead.created event from everywhere + Lead Confirmation trigger seed
Files: 12
Verify: every lead-capture source publishes; seeded trigger fires for any source; bulk-import excluded by default; existing orgs backfilled.
Tests: 12 pytest cases.
Awaiting "proceed".
```
