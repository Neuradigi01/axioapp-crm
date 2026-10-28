# Bulk Import (Leads)

Adds a CSV/XLSX bulk-import surface that lets an Owner or Admin migrate leads from a competing CRM (Zoho, HubSpot, Salesforce, Freshsales, a custom Excel export) into FurnitureCRM. The user picks the source platform, the system suggests a column mapping from a saved preset, the user confirms or tweaks the mapping, previews the first rows, then commits. Bad rows are reported back as a downloadable error CSV; good rows land as leads with `source='bulk_import'`.

## Why this exists

The single biggest barrier to a new customer switching CRMs is **getting their existing leads in**. A manual re-key is a non-starter past a few dozen rows. Every competing CRM exports CSV/XLSX with mostly-overlapping column names — `name | full_name | Customer Name | Contact Name`, `phone | mobile | Phone Number | Mobile Number`, etc. A mapping UI with per-platform presets shrinks the migration from a multi-day sales-ops task to a five-minute self-service flow.

Per the manager spec (2026-05-22): the user picks the platform from a dropdown, and we provide column-mapping options against their actual data.

| Gap | What's missing today |
|---|---|
| **No bulk endpoint** | The only way to create leads programmatically is one `POST /leads` per row. A migration with 5,000 leads = 5,000 round-trips and no error report. |
| **No file upload surface** | The frontend has no file-upload page or component for leads. |
| **No mapping UI** | Even if a `POST /leads/bulk` existed, the customer's CSV columns don't match our schema; they need a UI to draw the lines. |
| **No source presets** | Every customer wastes ~5 minutes re-doing the same Zoho-export mapping. A per-platform preset removes that. |
| **No dedup** | Importing the same export twice would create duplicates. Realistic risk — orgs run repeat exports during testing. |
| **No import history** | After commit there is no way to see what was imported when, by whom, with what errors. |

## What this does NOT do

- **Does not import contacts, deals, or activities.** Lead-only for v1. Contacts ride along if the lead row carries contact fields, but no separate contact-import flow.
- **Does not provide two-way sync** with Zoho/HubSpot/etc. One-shot migration only. Continuous sync is out of scope forever (would require maintaining adapters for every platform's API).
- **Does not import attachments / notes / call recordings.** Tabular CSV/XLSX only.
- **Does not run on the public internet** — the upload endpoint is behind admin auth, not the embed-key path used by the widget track.
- **Does not allow custom field creation during import.** Custom fields must exist in the org's `custom_field_definitions` *before* import; if a column maps to an unknown custom field, the mapping UI flags it and lets the user skip the column or jump to the Custom Fields page to add it first.
- **Does not touch `features/admin/`.**

## Acceptance criteria

A new Owner, on a fresh org, can:

1. Navigate to `/user/leads/import` → see a file picker + a "Source platform" dropdown (`Zoho | HubSpot | Salesforce | Freshsales | Generic CSV | Custom`).
2. Upload a 1,000-row Zoho lead export → page advances to a mapping screen showing every CSV column on the left, a dropdown of CRM fields on the right, pre-filled from the Zoho preset.
3. Tweak two mappings, mark one column as "Ignore", click "Preview" → see the first 5 rows rendered as they would land in the CRM, with red highlights on validation errors.
4. Click "Import" → progress indicator → completion screen showing `957 imported, 32 duplicates skipped, 11 errors (download error CSV)`.
5. Navigate to `/user/leads` → 957 new rows visible, each with the green-ish `Bulk import` badge from the manual-lead-entry track.
6. Re-upload the same file → completion shows `0 imported, 1,000 duplicates skipped` (dedup works on phone + email).
7. Navigate to `/user/leads/import/history` → see both import runs listed with timestamp, source platform, counts, and download links for the error CSVs.
8. As an Employee (no `leads.import` permission), `/user/leads/import` is hidden from the menu and a direct visit shows the Access Denied page.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: `lead_imports` table + upload endpoint](step-1-backend-imports-table-and-upload.md) | Pending | ~1 day |
| 2 | [Backend: parse + validate + dedup + commit (Celery job)](step-2-backend-celery-import-job.md) | Pending | ~1 day |
| 3 | [Backend: `import_presets` per source platform](step-3-backend-source-platform-presets.md) | Pending | ~½ day |
| 4 | [Frontend: upload page + source-platform selector](step-4-frontend-upload-page.md) | Pending | ~½ day |
| 5 | [Frontend: column-mapping UI + preview](step-5-frontend-mapping-ui.md) | Pending | ~1 day |
| 6 | [Frontend: import history + error-report download](step-6-frontend-import-history.md) | Pending | ~½ day |

**Total: ~4½ working days.** Each step verifiable in under 30 min per Rule 8; stop-and-report per Rule 9.

## Dependencies

- Manual Lead Entry — Step 1 of that track (the `lead.source` enum) must be in place; this track writes `source='bulk_import'`.
- Phase 1.5 (permissions) — adds a new `leads.import` key gating the page + API.
- Phase 1.7 (audit logs) — every import emits `lead.import.started`, `lead.import.completed`, and one `lead.created` per row (reuses the manual-entry event).
- Phase 2.11 / 2.12 (Leads backend + frontend) — the import lands rows on the existing `leads` table; the UI lives under `/user/leads/...`.
- Celery + Redis are already wired (per the locked stack); Step 2 adds a new task to the existing worker.

## File budget

| Area | Files |
|---|---|
| Backend Step 1 | 1 migration + 3 new (`leads/imports/{models,schemas,router}.py`) + 1 modified (`leads/__init__.py`) + 1 modified (`permissions/registry.py` for `leads.import`) + 1 test |
| Backend Step 2 | 1 new (`leads/imports/parser.py`) + 1 new (`leads/imports/tasks.py` Celery) + 1 new (`leads/imports/dedup.py`) + 1 modified (`leads/imports/service.py`) + 2 tests |
| Backend Step 3 | 1 migration + 2 new (`leads/imports/presets.py` + seed file) + 1 modified router + 1 test |
| Frontend Step 4 | 3 new (`features/user/core/leads/import/upload-page.component.{ts,html}` + `imports-api.service.ts`) + 1 modified (`leads.routes.ts`) |
| Frontend Step 5 | 2 new (`mapping-page.component.{ts,html}`) + 1 new (`mapping-row.component.ts`) |
| Frontend Step 6 | 2 new (`history-page.component.{ts,html}`) |

**Total ~25 files across 6 steps.** Each step ≤ 6 files, well inside rule-8.

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Imported rows carry `source='bulk_import'` and `actor_user_id` of the uploader | Step 2's commit logic; can never be overridden by mapping. |
| Mapping cannot target system-managed columns | `id`, `org_id`, `created_at`, `updated_at`, `source` are excluded from the mappable-targets list returned by the API. |
| Dedup is based on a configurable key set, default `(normalized_phone, lowercased_email)` | Step 2 — `dedup.py` exposes the key as configurable to support future per-org strategy, but ships with this default. |
| Import never partially commits across rows | Step 2 commits each row in its own SAVEPOINT; failures of one row don't rollback the others. Errors land in the error CSV; successes are durable. |
| File uploads have hard caps | 10 MB / 50,000 rows. Larger files are rejected at the upload endpoint with a clear error. |
| Files are stored on disk under `./storage/{org_id}/imports/{import_id}/source.{csv,xlsx}` | Reuses the `StorageBackend` interface from CLAUDE.md (no S3). |
| `org_id` on every new table | `lead_imports` and `import_presets` both carry it; RLS attached in the same migration. |
| Audit events emitted on start + complete + per-row | Reuses `lead.created` from the manual-entry track for per-row events. |

## Self-check against the 10 rules

- Rule 1: Pure core. No pack touched.
- Rule 2: Both new tables carry `org_id` + RLS in the same migration.
- Rule 3: Custom fields layer untouched; mapping UI consumes the existing `custom_field_definitions` to expose custom targets for mapping.
- Rule 4: Mapping UI is itself a dynamic form — it reads available targets from `GET /leads/import/targets` rather than hardcoding.
- Rule 5: New menu item registers via the existing sidebar registry; no compile-time furniture coupling.
- Rule 6: One new permission key (`leads.import`); granted to Owner + Admin templates.
- Rule 7: `pack.yaml` unaffected. The pack may later contribute extra source-platform presets (e.g. a "Pepperfry-CSV" preset for furniture retailers migrating from Pepperfry seller exports), but the registry pattern is composable.
- Rule 8: 25 files across 6 steps, each step ≤ 6 files.
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs. The error CSV is downloadable from day one.

## After this track

- Self-service migrations are unblocked. Customers can land 5,000 leads in 5 minutes.
- The `import_presets` registry pattern carries over to the bulk-import-contacts track (post-launch, not in this plan).
- The mapping UI shape proves out for the future "field mapping for ad-integration webhook payloads" surface in the ad-integrations track.
