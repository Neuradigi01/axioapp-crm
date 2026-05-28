# Step 3.5.10 — XLSX/CSV contact import: upload + dry-run + column mapping + commit

**Goal:** Operator uploads a spreadsheet → backend parses headers → returns suggested column mapping + a per-row dry-run preview → operator confirms → rows are inserted into contacts + (optionally) into a new static group.

**Phase:** 3.5
**Depends on:** 3.5.7 (static groups — import can create one)
**Status:** PROPOSED — awaiting "begin"

After this step the operator can take `sales_leads_q3.xlsx` (full_name, phone, email columns + custom columns) and turn it into 200 new contacts + a "Q3 Sales Leads" static group, in 3 clicks.

---

## Scope

### In-scope

**Backend:**
- New table `contact_imports` (audit trail): `id`, `org_id` (TenantScoped), `filename`, `uploaded_by_id`, `row_count`, `success_count`, `error_count`, `error_log` (JSONB — per-row errors), `created_group_id` (FK, nullable), `status` (uploading/dry_run/committed/failed), `created_at`.
- Migration `0065_contact_imports.py`.
- New endpoints under `/api/v1/contacts/imports`:
  - `POST /upload` — multipart form, returns `{import_id, suggested_mapping: {column_name: contact_field}, sample_rows: [...]}`. Parses XLSX (openpyxl) or CSV (stdlib csv). Files stored at `./storage/{org_id}/imports/{import_id}.xlsx` via `StorageBackend`.
  - `POST /{id}/dry-run` — body: `{mapping: {csv_col: contact_field}, create_group: boolean, group_name?: string}`. Returns `{will_insert: N, will_update: M, errors: [{row, reason}]}`. Phone deduplication detection.
  - `POST /{id}/commit` — same body. Idempotent on `import_id`. Inserts contacts in batches of 100, creates static group if requested.
- Reuse existing column-mapping registry from `leads.imports.targets` (Phase 5 work — same pattern).

### Out-of-scope

- Progress streaming (WebSocket) → P2. v1 returns `{job_id}` and frontend polls.
- Update existing contacts on phone match → v1 always inserts (skip on dup); update-mode is P2.
- Custom field mapping → covered if `custom_data.<key>` is offered as a target.

---

## Files to touch

### Created (~5)
- `API/alembic/versions/0065_contact_imports.py`
- `API/src/app/core/contacts/imports/models.py`
- `API/src/app/core/contacts/imports/service.py`
- `API/src/app/core/contacts/imports/router.py` + `schemas.py`

### Modified (1)
- `API/src/app/main.py` — wire router

**File budget:** ~6 files.

---

## Plan

1. Upload: stream file to local storage, parse headers, suggest mapping by fuzzy matching column names against `contact.*` field labels.
2. Dry-run: simulates insert without writing, detects phone dupes, returns errors with row numbers.
3. Commit: batch insert; on any per-row error, continues + appends to `error_log`.

---

## Pre-implementation question

**Q:** File size limit?

- **(a) 5 MB / ~10,000 rows** — covers 99% of furniture-store import volumes
- **(b) 50 MB / ~100,000 rows** — power-user case but needs streaming parser

**Recommendation: (a)** — keeps memory cap predictable. Operators with bigger files split or run twice.

---

## Verification + Self-check + Stop & report — standard
