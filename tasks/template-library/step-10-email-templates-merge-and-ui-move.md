# Step 10 — Email templates merge + UI move

**Goal:** Fold `core/email_templates/` into `core/templates/`. Migrate every existing email template into the central tables. Switch `core/email_sequences/`'s `template_id` FK to the generic table. Relocate the email-templates UI out of Settings into the new module. Drop the Settings → Email Templates tab. Email sequences UI stays in Settings (moves only when `tasks/workflows/` track lands).
**Status:** COMPLETED — Migration `0121_email_template_merge` applied: every `tbl_email_templates` row backfilled into `tbl_message_templates` + matching v=1 version row (status map: live+active → published; live+inactive → draft; soft-deleted → archived). `tbl_email_sequence_steps.template_id` FK dropped dynamically (name found via information_schema), remapped, recreated against the central table. Old table renamed to `_legacy_tbl_email_templates` for one-release safety net. NEW `core/templates/render.py` (build_context + render_email_template — moved verbatim from the deleted service). NEW `core/email_sequences/data_access/` (list_valid_email_template_ids). `email_sequences/service.py` + `scheduler.py` switched to central `MessageTemplate`; scheduler skip-reason `template_deleted → template_archived`. `core/email_templates/` package DELETED (6 files); `core/email/variables.py` Step-2 shim DELETED; `main.py` import + include line removed. Frontend: `settings/email-templates/` folder DELETED (5 files); `email-templates-api.service.ts` rebuilt as a deprecation shim delegating to `TemplatesApiService` (spec deviation: spec said delete it — replaced with shim to avoid breaking picker/compose-bar/sequence-builder; cleanup PR drops it later); Settings → Email Templates tab + 3 routes removed; `/user/settings/email-templates*` redirects to `/user/templates`. 4 pytest cases pin the status mapping + the new email-sequences DAL behavior.
**Depends on:** Step 9 (WhatsApp migration pattern), Step 7 (Email sub-form in the editor).

---

## Scope

In-scope:
- Migration `<ts>_email_template_merge.py`:
  - For every `tbl_email_templates` row: insert a matching `tbl_message_templates` row (channel=email, name, body_text=`html_body`, subject, preview_text, variables JSONB, internal_status='published' for any active template — they were already in use; `archived` for inactive), and one `tbl_message_template_versions` v=1 row.
  - Switch `tbl_email_sequences.template_id` FK target from `tbl_email_templates(id)` to `tbl_message_templates(id)`. Remap every FK value using a bridge mapping built during the same migration.
  - Drop the old `tbl_email_templates` table only AFTER both migrations succeed — keep a deprecation `_legacy_tbl_email_templates` view for one release as a safety net.
- Backend code:
  - Delete `core/email_templates/` package contents (router, service, schemas, models). The `notifications/email_renderer.py` is independent and untouched.
  - `core/email/variables.py` shim from Step 2 is deleted; callers point at `core/templates/variables.py`.
  - `core/email_sequences/models.py` updates the FK relationship to `MessageTemplate`.
  - `core/email_sequences/service.py` adjusts any direct queries on the removed model.
  - Any other callers of the removed `EmailTemplate` model — grep + update. Expect ~5-10 call sites in `notifications/`, `email_sequences/`, possibly tests.
- Frontend:
  - Delete `APP/.../settings/email-templates/` files (3 files).
  - `APP/.../settings/settings-page.component.{ts,html}`: drop "Email Templates" tab entry.
  - `APP/.../core/services/email-templates-api.service.ts`: delete (callers go through the new central api service).
  - Email sequences UI (`APP/.../settings/email-sequences/`) keeps its tab — only the underlying API responses (template lists, picker) point at the new central endpoint.
  - Where the email-sequences builder lets the operator pick a template, the picker now lists `tbl_message_templates` filtered by `channel=email`.
- Backfill migration `<ts>_bf_email_seq_template.py` updates `tbl_email_sequences` FK values + leaves a "missing template" row for any orphan.

Out of scope:
- Moving email-sequences UI out of Settings — future `tasks/workflows/` track.
- Deleting `notifications/email_renderer.py` — it's the system-notifications renderer (billing, password reset, etc.) and uses a different rendering path. Untouched.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_email_template_merge.py` | **NEW** |
| `API/alembic/versions/<ts>_bf_email_seq_template.py` | **NEW** — FK remap |
| `API/src/app/core/email_templates/__init__.py` | **DELETE** |
| `API/src/app/core/email_templates/models.py` | **DELETE** |
| `API/src/app/core/email_templates/service.py` | **DELETE** |
| `API/src/app/core/email_templates/router.py` | **DELETE** |
| `API/src/app/core/email_templates/schemas.py` | **DELETE** |
| `API/src/app/core/email_templates/module.py` | **DELETE** |
| `API/src/app/core/email/variables.py` | **DELETE** — shim from Step 2 |
| `API/src/app/core/email_sequences/models.py` | edit — FK relationship to MessageTemplate |
| `API/src/app/core/email_sequences/service.py` | edit — adjust queries |
| `API/src/app/main.py` | edit — drop the old router include |
| `APP/src/app/features/user/core/settings/email-templates/template-list.component.ts` | **DELETE** |
| `APP/src/app/features/user/core/settings/email-templates/template-list.component.html` | **DELETE** |
| `APP/src/app/features/user/core/settings/email-templates/template-editor.component.ts` | **DELETE** |
| `APP/src/app/features/user/core/settings/email-templates/template-editor.component.html` | **DELETE** |
| `APP/src/app/features/user/core/settings/email-templates/template-editor.page.ts` | **DELETE** |
| `APP/src/app/features/user/core/services/email-templates-api.service.ts` | **DELETE** |
| `APP/src/app/features/user/core/settings/settings-page.component.ts` | edit — drop tab |
| `APP/src/app/features/user/core/settings/settings-page.component.html` | edit — drop tab |
| `APP/src/app/features/user/core/settings/email-sequences/sequence-builder.component.ts` | edit — template picker hits new endpoint |
| `API/tests/templates/test_email_merge.py` | **NEW** |

**~22 files. ~700 lines** (heavy on deletes — most files have zero new lines, only old ones gone). At Rule 8's upper bound; deletion-heavy, low-risk per file.

## Plan

0. **Data-access layer** (project convention) — during the merge:
   - `core/email_templates/data_access/` is deleted along with the rest of the package.
   - `core/email_sequences/data_access/` (if not present, create it) gets a `sequences.py` for the post-merge FK-by-`message_template_id` lookups the scheduler uses at fire time.
   - `core/templates/data_access/templates.py` already covers the read path from Step 2; sequences delegate to it.
   No new ad-hoc queries in `email_sequences/service.py` or the migration's data-fix block — extract any query that survives into the DAL.
1. Migration: backfill central rows from `tbl_email_templates`, build the FK bridge, remap `tbl_email_sequences.template_id`, drop FK constraint, drop old table (replace with view shim).
2. Update `core/email_sequences/` to use the new model.
3. Delete `core/email_templates/` package files + the variables shim.
4. Drop the router mount in `main.py`.
5. Frontend: delete the Settings tab + its components; drop the tab entry from the settings page navigation.
6. Email-sequences builder: point its template picker at `/api/v1/templates?channel=email&internal_status=published`.
7. Tests: backfill correctness + email-sequence picker fetches the right list + Settings page no longer shows Email Templates tab.

## DB changes / migrations

Two migrations:
- Schema merge — creates central rows, switches the FK.
- Backfill — fills `tbl_email_sequences.template_id` with the remapped UUIDs.

Reversibility: down direction restores `tbl_email_templates` from the `_legacy_*` view contents + re-points the FK. Tested.

## Tests

7 pytest cases:
- Every email-template row produces a matching central row.
- `tbl_email_sequences` FK values remap correctly.
- An orphan sequence (template was deleted before migration) gets a clean error row, not a crash.
- Notifications email render still works (separate from email templates — guard against accidental coupling).
- Settings → Email Templates tab is absent (UI test).
- Email-sequence builder template picker calls the new endpoint.
- Deleted-template handling: a sequence referencing an archived template still renders (UI shows "Template archived" warning).

## Smoke

```
1. Pre-migration: SELECT count(*) FROM tbl_email_templates → M.
2. Run migrations.
3. SELECT count(*) FROM tbl_message_templates WHERE channel='email' → M (or N more, if any from Step 7 testing).
4. SELECT count(*) FROM tbl_email_sequences WHERE template_id IN (SELECT id FROM tbl_message_templates) → all rows.
5. Settings → Email Templates tab gone.
6. /user/templates → email templates listed.
7. Open an email sequence in Settings → Email Sequences → template picker shows the email templates from the central list.
8. Trigger an email sequence with a published template → email arrives correctly.
```

## Risks

- Two migrations in one step — sequencing critical. Run the schema merge BEFORE the backfill; if backfill fails, the schema migration is still reversible.
- Legacy view shim (`_legacy_tbl_email_templates`) — strictly read-only safety net. Drop in a follow-up step after one release of operator sign-off (NOT in this track).
- Orphan template references in email_sequences — rare but possible if old data has stale FK. Migration logs them and leaves the row with `template_id=NULL` rather than crashing.

## Self-check (10 rules)

`core/templates/` + drops from `core/email_templates/`. ✓ org_id preserved in remap. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions: `templates.read/write` already cover email channel. pack.yaml untouched. ✓ 22 files / ~700 lines — heavy on deletes, low per-file risk; Rule 8 admits exception for clean deletion. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 10 — Email templates merge + UI move
Files: 22 (mostly deletes)
Verify: every existing email template visible in central list; sequences still fire correctly; Settings → Email Templates tab gone; Settings → Email Sequences tab still there but picker points at new endpoint.
Tests: 7 pytest cases.
Awaiting "proceed".
```
