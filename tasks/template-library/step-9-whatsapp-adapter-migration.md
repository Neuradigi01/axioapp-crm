# Step 9 — WhatsApp adapter migration

**Goal:** Rehouse existing WhatsApp templates under the new central library. Backfill every row of `tbl_whatsapp_templates` into `tbl_message_templates` with a matching link; route new WA template creation through the new module; deep-link `/user/whatsapp/templates` into the new editor filtered by `channel=whatsapp`. Wire external submission (Submit to Meta).
**Status:** Pending
**Depends on:** Steps 1-8 (full module live + UI functional for WA channel). Existing `core/integrations/whatsapp/templates_*.py` (kept as polymorphic extension).

---

## Scope

In-scope:
- `tbl_whatsapp_templates` stays as the **polymorphic extension** carrying Meta-specific fields (header type, button payloads, language code, components JSON, Meta `submission_status`, `rejection_reason`, `submitted_by_user_id`, `submitted_at`). Linked to `tbl_message_templates` via `tbl_message_templates.external_provider_id` and a reciprocal `tbl_whatsapp_templates.message_template_id` FK.
- Migration `<ts>_wa_template_backfill.py`:
  - Adds `tbl_whatsapp_templates.message_template_id UUID NULL REFERENCES tbl_message_templates(id) ON DELETE CASCADE` + index.
  - For every existing `tbl_whatsapp_templates` row: insert a matching `tbl_message_templates` row (channel=whatsapp, name=existing name, body_text=body, current_version=1, internal_status mapped from existing Meta `submission_status` — `draft→draft`, `pending_review→in_review`, `approved/paused/disabled→approved`, `rejected→draft`); insert a matching `tbl_message_template_versions` v=1 row; backfill `tbl_message_templates.external_provider_id` from `meta_template_id` + `external_status` from the Meta status.
  - Sets the new `message_template_id` link.
  - Migration is reversible (down drops the new column + new rows; existing WA template rows untouched).
- `core/integrations/whatsapp/templates_service.py` extension:
  - `submit_for_approval` now drives BOTH the WA-specific Meta submit AND the central `external_status='pending'` transition.
  - `apply_template_status_update` (already exists for Meta webhooks) syncs the central `external_status` whenever the WA-specific status changes.
- `core/templates/external_submission.py`:
  - `submit_external(org_id, template_id, user_id)` — channel-dispatch. For WA: calls into `whatsapp/templates_service.submit_for_approval`. For SMS/FB/IG/email/push: raises `ExternalSubmissionNotSupported`.
  - `POST /api/v1/templates/{id}/submit-external` endpoint, gated on `templates.submit_external`.
- `core/templates/router.py`:
  - `GET /api/v1/templates/{id}/external-status` returns `{status, last_synced_at, rejection_reason}`. Live read against the WA extension table for WA templates.
  - `POST /api/v1/templates/{id}/sync-external` — admin re-sync (calls Meta `/message_templates` to refresh status).
- Frontend:
  - `APP/.../core/templates/editor/wa-form.component.ts` extended with "Submit to Meta" button — visible when channel=WA + status=approved-internal + external_status in (`n_a`, `rejected`).
  - `APP/.../core/whatsapp/templates/whatsapp-templates.page.ts` becomes a deep-link wrapper that routes to `/user/templates?channel=whatsapp` (preserves the existing URL for muscle memory; existing wizard component stays as a fallback for one release, removed in a follow-up cleanup PR).
- `core/integrations/whatsapp/templates_router.py` endpoints unchanged — they continue to work read-only against the WA extension; internally the central tables get updated via shared service.

Out of scope:
- Removing the existing WA template UI files (`whatsapp/templates/*.component.*`). They stay for one release; cleanup PR after smoke. Defer the delete to a follow-up step in this track if needed.
- SMS DLT external submission (Step 12).
- Background sync polling (Step 14).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_wa_template_backfill.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | edit — add `message_template_id` FK + relationship |
| `API/src/app/core/integrations/whatsapp/templates_service.py` | edit — write through to central tables |
| `API/src/app/core/templates/external_submission.py` | **NEW** |
| `API/src/app/core/templates/router.py` | edit — `submit-external`, `external-status`, `sync-external` endpoints |
| `APP/src/app/features/user/core/templates/editor/wa-form.component.ts` | edit — Submit-to-Meta button |
| `APP/src/app/features/user/core/whatsapp/templates/whatsapp-templates.page.ts` | edit — deep-link redirect to `/user/templates?channel=whatsapp` |
| `API/tests/templates/test_wa_backfill.py` | **NEW** |

**~8 files. ~500 lines.**

## Plan

0. **Data-access layer** (project convention) — new lookups go into:
   - `core/integrations/whatsapp/data_access/templates.py` for WA template reads + `message_template_id` joins.
   - `core/templates/data_access/templates.py` extended with `get_by_external_provider_id(...)` for Meta-status webhook routing.
   Service / workflow / submission helpers stay as-is for writes + Meta API calls; they delegate reads to the DAL.
1. Migration first — backfill carefully (single transaction, dry-run on a test DB clone). Each existing WA template gets one new central row + one version row.
2. WA service: write through to central tables on every operation. Internally use the central service for inserts/updates; the WA extension carries only the Meta-specific delta.
3. External submission router: thin wrapper.
4. UI: deep-link WhatsApp templates page → central templates page filtered by channel.
5. Submit-to-Meta button in editor.
6. Tests: backfill correctness (every WA row produces a central row with the right status mapping), submit flow end-to-end with mocked `MetaGraphClient`.

## DB changes / migrations

One migration: adds `message_template_id` FK column to `tbl_whatsapp_templates` + backfills `tbl_message_templates` rows + backfills `tbl_message_template_versions` v=1 rows + links them. Reversible.

## Tests

8 pytest cases:
- Backfill produces one central row per existing WA template.
- Backfill produces one v=1 version row per central row.
- Status mapping: `pending_review → in_review`, `approved → approved`, etc.
- `submit_external` calls `MetaGraphClient.submit_template` with the right payload.
- `submit_external` flips `external_status` to `pending` on success.
- `apply_template_status_update` (Meta webhook) syncs `external_status` on the central row.
- New WA template created via `POST /templates` produces both a central + extension row in one transaction.
- Submitting an unrelated channel returns 422.

## Smoke

```
1. Pre-migration: SELECT count(*) FROM tbl_whatsapp_templates → N.
2. Run migration → SELECT count(*) FROM tbl_message_templates WHERE channel='whatsapp' → N.
3. SELECT count(*) FROM tbl_message_template_versions → N (one v=1 per).
4. /user/whatsapp/templates → redirects to /user/templates?channel=whatsapp → list shows the same N templates with badges.
5. Open one approved-internal template → Submit to Meta button visible → click → POST submit-external → external_status flips to pending; Meta receives the submission.
6. Meta webhook fires status update → central row external_status flips to approved.
7. Existing legacy /api/v1/integrations/whatsapp/templates/manage endpoints still work.
```

## Risks

- Backfill on a tenant with hundreds of WA templates — single-transaction migration is fine at this scale; if a tenant has thousands, batch in 500-row chunks.
- The reciprocal FK creates a soft cycle (central → external_provider_id text, extension → message_template_id UUID). Documented as two-way navigation; deletion handled by CASCADE on the extension side + soft archive on the central side.
- The existing WA templates UI (`whatsapp/templates/*.component.*`) overlapping with the new module is intentional for one release; delete in a follow-up PR after operator sign-off.

## Self-check (10 rules)

`core/templates/` + `core/integrations/whatsapp/`. ✓ org_id on all new rows. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already in place. ✓ pack.yaml untouched. ✓ 8 files / ~500 lines. ✓ Stop-report. ✓ No TODOs (deferred WA UI delete tracked as follow-up). ✓.

## Stop & report

```
Step 9 — WhatsApp adapter migration
Files: 8
Verify: every existing WA template appears in the central list with correct status; Submit-to-Meta works end-to-end; legacy WA endpoints still serve.
Tests: 8 pytest cases.
Awaiting "proceed".
```
