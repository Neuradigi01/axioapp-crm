# Step 8 — Frontend: per-integration field mapping editor + integration status dashboard

**Goal:** Build the per-form field mapping editor (when an Owner opens a subscribed form, they edit the `{ad_field → crm_field}` map) and the integration status dashboard (last delivery timestamp per subscription, success/failure counts, the DLQ list with replay). Closes out the four-channel lead-ingestion track.
**Track:** Ad Integrations
**Status:** Pending
**Depends on:** Step 7 (integrations page exists, subscription rows exist), Steps 3 + 5 (DLQ table exists, replay endpoint exists), Bulk Import Step 3 (mapping-target endpoint reused).

---

## Scope

In-scope:

- **Per-form field mapping editor:**
  - From Step 7's form list, each subscribed form has an "Edit mapping" button → opens a modal/page `/user/settings/integrations/{provider}/forms/{subId}/mapping`.
  - Loads the ad-platform's known field list (from `integration_subscriptions.field_mapping` keys we know from the ad payload schema, plus the form's defined fields fetched via the provider API on first open).
  - For each ad field, a dropdown of CRM targets (reuse `GET /leads/import/targets` from the bulk-import track).
  - Sensible defaults pre-filled:
    - `FULL_NAME` / `full_name` → `contact.full_name`
    - `PHONE_NUMBER` / `phone_number` → `contact.phone`
    - `EMAIL` / `email` → `contact.email`
    - `WORK_EMAIL` → `contact.email`
    - `(everything else)` → `Ignore`
  - "Use defaults" button restores the above.
  - "Save" persists via `PUT /api/v1/integrations/subscriptions/{id}/mapping`.

- **Integration status dashboard panel** at the top of the Integrations page (above the provider cards):
  - "Last delivery: {provider} — 4 minutes ago" with a green dot.
  - "DLQ: 3 deliveries failed in the last 24 hours" — link expands the DLQ list inline.

- **DLQ list (inline expandable):**
  - Table: time, provider, integration account, payload preview (first 100 chars JSON), error message, retries attempted.
  - "Replay" button per row → POST `/api/v1/integrations/dlq/{id}/replay` → row removed on success (200) or stays with updated error on failure.
  - "Discard" button (soft-delete) — sets `replayed_at = now()` with a special `replayed_by = NULL` to mean "discarded without replay" (keeps audit trail).

- **Routing config widget (small):**
  - Just a card showing "Lead assignment strategy: Round-robin" with a disabled dropdown (only one option for v1).
  - Hooked to `GET /tenants/me/routing-config` and `PUT` (no-op until more strategies added).

- New small backend endpoints needed:
  - `PUT /api/v1/integrations/subscriptions/{id}/mapping` — update the JSONB mapping.
  - `GET /api/v1/integrations/dlq?provider=&page=` — paginated.
  - `POST /api/v1/integrations/dlq/{id}/discard` — soft-discard.
  - `GET /api/v1/integrations/status` — single endpoint returning `{providers: [{provider, last_delivery_at, last_delivery_status, deliveries_24h: {accepted, dlq}}]}` for the dashboard panel.

Out of scope:

- Per-campaign routing rules (e.g. all leads from Campaign X go to user Y) — Settings has the slot, no engine yet.
- Editing the field list of a form (that lives in Google/Meta UIs, not ours).
- DLQ bulk replay.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/integrations/router.py` | modified — add `PUT /subscriptions/{id}/mapping`, `GET /dlq`, `POST /dlq/{id}/discard`, `GET /integrations/status` |
| `api/src/app/core/integrations/service.py` | modified — supporting methods |
| `api/tests/test_integrations_status_and_mapping.py` | created |
| `app/src/app/features/user/core/settings/integrations/field-mapping-editor.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/field-mapping-editor.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/integration-status.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/integration-status.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/dlq-list.component.ts` | created |
| `app/src/app/features/user/core/settings/integrations/dlq-list.component.html` | created |
| `app/src/app/features/user/core/settings/integrations/integrations-api.service.ts` | modified — add new endpoint wrappers |
| `app/src/app/features/user/core/settings/integrations/integrations-page.component.html` | modified — slot the status component + dlq list |

**11 files.** Marginally over rule-8. Implementer can split into 8a (backend + mapping editor) and 8b (status dashboard + DLQ UI) if diff gets heavy.

## Plan

1. (Backend) Add the four new endpoints. `GET /integrations/status` aggregates from `audit_log` (or a small materialised counter table if audit log queries get slow). For v1, query audit log — `events` already index well by `(org_id, event_type, created_at)`.
2. (Backend) Map mapping-target endpoint is already from bulk-import — reused as-is.
3. (Frontend) Build `FieldMappingEditorComponent`. Standalone, signals-based. Inputs: `subscriptionId`, `provider`, `formFields[]`. Loads targets + current mapping; renders the editor table; Save button.
4. Build `IntegrationStatusComponent` — small card with the live status. Polls `/integrations/status` every 30s.
5. Build `DlqListComponent` — paginated table with Replay/Discard buttons. Confirm modals on both.
6. Slot status + DLQ into `IntegrationsPageComponent` above the provider cards.
7. Tests for the new endpoints; manual smoke for the UI.

## Tests

`api/tests/test_integrations_status_and_mapping.py`:

- **PUT mapping persists:** PUT `{mapping: {FULL_NAME: "contact.full_name"}}` → GET subscription row reflects.
- **PUT mapping rejects unknown CRM target:** mapping with `{X: "not.a.real.field"}` → 422.
- **GET status returns expected shape:** seed audit-log events; status response includes correct counts per provider.
- **GET DLQ paginates + filters by provider.**
- **POST /dlq/{id}/replay re-enqueues** (in test, with eager Celery).
- **POST /dlq/{id}/discard sets `replayed_at` with `replayed_by=NULL`.**
- **RLS on DLQ + mapping.**
- **Permission gate on all new endpoints.**

## Smoke (browser)

```
1. Continuing from Step 7 smoke: a Google form is subscribed.
2. Click "Edit mapping" on the form row → modal opens with the form's fields listed,
   defaults pre-filled where possible.
3. Change EMAIL → contact.email (was previously Ignore). Save. Toast.
4. Send a fresh test lead from Google Ads with email populated. Verify the lead row
   in /user/leads now carries the email (was blank before the mapping change).
5. On the Integrations page top: status panel shows "Last Google delivery: <recent>".
6. Force a failure: temporarily revoke the Google token (or change the integration
   row's status to 'expired' in the DB). Trigger a webhook. Lead processing fails,
   goes to DLQ. Within 30s, status panel updates: "DLQ: 1 delivery failed."
7. Click "DLQ list" → table shows the failed delivery. Click Replay (after restoring
   the token). Row disappears, lead created.
8. Test Discard: cause another failure, click Discard → confirm modal → row stays
   with discarded indicator.
9. Routing config card shows "Round-robin" disabled.
10. As Employee → all this is hidden.
```

## Risks

- **Status endpoint cost:** querying audit log every 30s per Owner viewing the page = trivial; if we materialise per-provider counters later, this becomes free.
- **Field-mapping editor for Meta:** Meta's form field names are user-defined (the page admin names them on the Meta form). We need to fetch the form definition once on first edit and cache the field list. Add `GET /integrations/meta/forms/{form_id}/fields` if not already covered by Step 4's listing endpoint.
- **DLQ row count growth:** add a polite "X+" cap on the dashboard if DLQ exceeds 50; users can drill into the list. The list itself paginates.
- **Replay race:** a row being replayed by user A and discarded by user B — last-writer-wins on `replayed_at`. Acceptable; rare.
- **Routing strategy dropdown is misleading if disabled:** add helper text "More strategies coming soon" so users don't think it's a bug.

## Rollback

Revert backend endpoints. Delete new frontend files. Integrations page reverts to Step 7's layout (no status, no DLQ, no mapping editor). Mapping rows persisted in DB are untouched — webhooks continue using whatever mapping was last saved.
