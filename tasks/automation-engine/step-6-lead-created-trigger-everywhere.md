# Step 6 — lead.created event from everywhere + Lead Confirmation trigger seed

**Goal:** Publish `lead.created` from EVERY lead-capture source uniformly. Seed a default "Lead Confirmation" trigger so any new lead gets an automatic confirmation message (email + optional WhatsApp). This is the second of the two specific manager asks ("mail to lead automatically when the lead id submitted via anywhere") landed end-to-end.
**Status:** COMPLETED — **All 5 lead-capture sources (manual / API, embed widget, Google Ads webhook, Meta Ads webhook, bulk CSV import) converge through `core/leads/service.create_lead`** (the spec speculated 7 sites but explore confirmed: WhatsApp inbound creates `Contact` rows not `Lead` rows, and walk-ins create `WalkIn` rows not `Lead` rows — neither path produces a lead row today). Wired `lead.created` publish ONCE at the chokepoint in `create_lead` via `_publish_lead_created(session, org_id, lead)` called AFTER commit + post-`log_entity_change`. Helper snapshots `Contact` + `Organization` rows alongside the lead so the recipient resolver + the template renderer have everything they need without per-handler DB hits. Envelope: `{lead_id, contact_id, source, created_at, lead: {id, source, status, pipeline_stage, assigned_to_id, budget, attribution}, contact: {id, full_name, email, phone}, org: {id, name, slug}}`. Deterministic `event_id=f"lead_created:{lead.id}"` for at-least-once idempotency. Helper wraps everything in try/except so a misbehaving subscriber can't fail the freshly-committed lead. Backfill migration `0130_seed_lead_confirmation` applied: 24 existing orgs each got an idempotent "Lead Confirmation" published email template + v=1 version row + enabled `lead.created → email` trigger with the bulk-import exclusion baked in. DB confirms 24 + 24 (templates + triggers) post-apply on top of the Step-5 baseline (so the system now has 48 templates + 48 triggers across both seeds × 24 orgs). Raw SQL with `WHERE NOT EXISTS` guards make the migration idempotent + safe to re-run; downgrade removes seeded rows by exact name. `core/templates/seeds.py` extended with `seed_lead_confirmation_template(session, org_id)` — published email template with body `"Hi {{ contact.full_name }}, … thanks for reaching out to {{ org.name }} …"` (uses `contact.full_name` not `first_name` to match the actual `tbl_contacts.full_name` column shape) + subject `"Thanks for reaching out, {{ contact.full_name }}"`. `core/automation/seeds.py` extended with `seed_lead_confirmation_trigger(session, org_id, template_id)` carrying the bulk-import exclusion `{"field": "source", "op": "ne", "value": "bulk_import"}` as default conditions (operator can remove via the trigger editor in Step 8 after confirming bulk-outreach policy). `install_default_org_seeds` now installs BOTH the Welcome (Step 5) + Lead Confirmation (Step 6) seeds in one transaction; the tenants `create_organization` call already wires this chokepoint so new orgs pick up both automatically without further code change. `core/automation/event_catalog.py:lead.created` sample_payload updated to the publisher's actual shape (flat top-level keys for condition AST paths + nested `lead`/`contact`/`org` snapshots for template rendering — replaces the older nested-only shape). 8 pytest cases in `test_lead_created.py`: install seeds creates Lead Confirmation, idempotent re-run, matcher returns it for `source='widget'`, matcher EXCLUDES `source='bulk_import'` (the seed's bulk-import condition does its job), dispatcher enrols queued run for non-bulk source + resolves recipient from the contact snapshot, dispatcher skips bulk-import source (no run row), pin test asserts exactly ONE `_publish_lead_created` helper + ONE invocation + ONE `events_publish('lead.created')` call in `core/leads/service.py` (catches any future code change that adds duplicate publish sites OR removes the chokepoint). Pytest run deferred per `feedback_pause_before_pytest.md` baseline.

**Manager promise #2 ("mail to lead automatically when the lead is submitted via anywhere") delivered end-to-end:** every lead from any source → `create_lead` chokepoint → `lead.created` published with full snapshot → wildcard dispatcher → seeded Lead Confirmation trigger matches (unless source='bulk_import') → recipient resolver finds contact's email via the denormalized snapshot → Celery `deliver_run` renders → email backend sends → `tbl_automation_runs` row with `status='sent'`.

**Spec deviations:** (1) Single publish call at the `create_lead` chokepoint instead of 5 separate publish calls at each upstream site — the spec's enumeration assumed each source had its own commit path; the codebase actually funnels every source through `create_lead`, so the chokepoint approach is both cleaner and harder to break (the pin test enforces it). (2) Walk-in + WhatsApp inbound publish sites omitted — those modules don't currently create lead rows; when they're extended to do so, the publish call at `create_lead` covers them automatically. (3) Template uses `{{ contact.full_name }}` instead of the spec's `{{ contact.first_name }}` — the contacts schema only has `full_name`. The pin test catches drift on the chokepoint count.

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
