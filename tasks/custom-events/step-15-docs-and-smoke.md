# Step 15 — Docs + contacts-source wiring + Ajay's Workspace end-to-end smoke

**Goal:** close the track: OpenAPI events section, "Fire your first event" quickstart, Zapier walkthrough, contacts source-filter + reporting groupings updated for `event_ingest`, and end-to-end smoke against Ajay's Workspace.
**Phase:** Custom Events track — step 15/17
**Depends on:** all prior steps
**Status:** Pending

## Scope

**In-scope:**
- OpenAPI tags + descriptions for `/api/v1/events/track`, `/api/v1/custom-events`, `/api/v1/api-keys`. Published as `/docs/api/events` public page (or wherever OpenAPI HTML rendering lives).
- `docs/quickstart/fire-your-first-event.md` — step-by-step: create event, create key, fire from cURL, see occurrence, wire workflow.
- `docs/quickstart/zapier-integration.md` — screenshots + text for setting up "Webhooks by Zapier" step with our endpoint.
- Contacts frontend:
  - Source-filter dropdown includes `Event ingest` as an option.
  - Contact detail sidebar shows `Created from event: <event name>` link when `created_from_event_id NOT NULL`.
  - Reporting page grouping "Contacts by source" surfaces `event_ingest` as a first-class bucket (avoids "Other").
- Retire shim files from Step 2 fold (old paths under `core/embed/` + `core/ai_assistants/public_context.py`).
- **End-to-end smoke against Ajay's Workspace** (org `41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com` per project memory):
  1. Login → Settings → API keys → Create `pk_live_*` events key (mode=live, hmac_required=true, auto_create_contacts=true).
  2. Save key.
  3. Settings → Custom events → Create `order.paid` with payload schema `{ order_id: string required, total: number required, currency: enum[USD,INR,EUR] required }`.
  4. Workflows → New workflow, trigger `custom.order.paid`, action Send Email "Thanks for order {{event.order_id}} — {{event.total}} {{event.currency}}".
  5. Fire event via cURL with HMAC signature.
  6. Verify: occurrence appears, workflow fires, email sent (or logged in dev mode).
  7. Verify contact auto-created with `source=event_ingest`.
  8. Post-smoke cleanup: delete key, delete event, delete workflow, delete test contact (per project memory — smoke tests against live/shared DB must clean up).

**Out of scope:**
- First-party Zapier app (future GTM track).
- Browser JS SDK (future).

## Files to touch
- Backend OpenAPI tags in `main.py` / router files.
- `docs/quickstart/fire-your-first-event.md` (new).
- `docs/quickstart/zapier-integration.md` (new).
- `APP/src/app/features/user/core/contacts/list.page.ts` (modified — add source filter option).
- `APP/src/app/features/user/core/contacts/detail.page.html` (modified — show `created_from_event`).
- `APP/src/app/features/user/core/reporting/contacts-by-source.component.ts` (modified — bucket).
- Retire shim files (deletions).
- `tasks/custom-events/CLEANUP-SMOKE-ARTIFACTS.sql` (new — per project memory pattern).

## Plan
1. OpenAPI polish.
2. Quickstart MDs.
3. Contacts UI wiring.
4. Retire shims.
5. Run smoke; document results.

## Tests to add
- Smoke document with pass/fail per step.
- `test_contacts_source_filter_includes_event_ingest`.

## Verification checklist
- Frontend: manual smoke on Ajay's Workspace, all 8 steps pass.
- Frontend: cleanup SQL executed post-smoke.
- Docs: quickstart renders correctly.
- Backend: `/docs/api/events` page shows all endpoints.

## Self-check
- [ ] Rule N/A / clean.
- [ ] Rule 10: shims retired here; no lingering half-done.
- [ ] Feedback: smoke test cleanup SQL written per project memory.

## Stop & report
Track complete. Final report per master template.
