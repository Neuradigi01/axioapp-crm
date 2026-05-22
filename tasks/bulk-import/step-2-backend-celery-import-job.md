# Step 2 — Backend: parse + validate + dedup + commit (Celery job)

**Goal:** When the user commits a mapping on an `awaiting_mapping` import, queue a Celery job that parses the file, validates rows against the mapped CRM fields, deduplicates against existing leads on `(normalized_phone, lowercased_email)`, commits good rows in per-row SAVEPOINTs, writes errors to an error CSV, and updates the import row to `completed` with counts.
**Track:** Bulk Import
**Status:** Pending
**Depends on:** Step 1 (table + upload), Manual Lead Entry Step 1 (`lead.source` enum).

---

## Scope

In-scope:

- New endpoint `POST /api/v1/leads/import/{id}/commit` taking the final `mapping: {csv_column: crm_field_key | null}` body. Validates the mapping (every target column exists; no system-managed targets), transitions `lead_imports.status` from `awaiting_mapping` → `mapping_committed`, persists `mapping` JSONB, and queues the Celery task.
- New endpoint `POST /api/v1/leads/import/{id}/cancel` — only allowed in `awaiting_mapping` or `mapping_committed`. Sets status to `cancelled`.
- Celery task `process_lead_import(import_id)`:
  - Loads the file from the stored path.
  - Iterates rows, builds a `LeadCreate` payload per row from the mapping, validates with Pydantic.
  - Calls `dedup.find_existing(org_id, normalized_phone, lowercased_email)` to skip dups.
  - For each non-dup, calls the existing `LeadService.create(...)` (the same path manual entry uses), forcing `source='bulk_import'` and `actor_user_id=uploader`.
  - Each row commits in its own SAVEPOINT; failures land in a row-level error list with `{row_number, csv_data, error_message}`.
  - Writes `errors.csv` to `./storage/{org_id}/imports/{import_id}/errors.csv`.
  - Updates `lead_imports.status` to `completed` (or `failed` for catastrophic errors), sets `counts` JSONB `{imported, duplicates_skipped, errors}`, sets `error_report_path`.
- Endpoint `GET /api/v1/leads/import/{id}/errors.csv` streams the error CSV (permission-gated, RLS-checked).
- `dedup.py` module exposing `normalize_phone(s)`, `lowercase_email(s)`, and `find_existing(session, org_id, phone, email) -> Lead | None`. The dedup key set is hardcoded to `(phone, email)` for this step; making it configurable is documented as a known follow-up.
- Audit events: `lead.import.completed` (with counts payload) at the end; per-row `lead.created` events emitted by `LeadService.create()` already (free reuse).
- Tests covering: happy path with mixed good/dup/error rows, mapping validation rejection, status transitions, error CSV format, idempotent Celery retry (a job that re-runs on an already-completed import is a no-op).

Out of scope:

- No frontend.
- No custom field creation from import — if a mapping targets a `custom_data.X` key whose definition does not exist in `custom_field_definitions`, the commit endpoint rejects with a clear "create this custom field first" error.
- No multi-tab / chunked import — the entire job runs as one Celery task. For 50k rows on local PG this completes well inside Celery's default timeout; if it ever grows beyond that, splitting into chunked sub-tasks is a future task.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/leads/imports/parser.py` | created — `parse_rows(storage_path, mapping) -> Iterator[ParsedRow]` |
| `api/src/app/core/leads/imports/dedup.py` | created — normalization + existing-lead lookup |
| `api/src/app/core/leads/imports/tasks.py` | created — Celery task `process_lead_import` |
| `api/src/app/core/leads/imports/service.py` | modified — add `commit_mapping(import_id, mapping, actor)`, `cancel(import_id, actor)`, `stream_errors(import_id) -> AsyncIterator[bytes]` |
| `api/src/app/core/leads/imports/router.py` | modified — `POST /{id}/commit`, `POST /{id}/cancel`, `GET /{id}/errors.csv` |
| `api/src/app/core/leads/imports/schemas.py` | modified — `LeadImportMapping`, `LeadImportCommit` |
| `api/src/app/core/audit/events.py` | modified (small) — declare `LEAD_IMPORT_COMPLETED` |
| `api/tests/test_lead_imports_process.py` | created |
| `api/tests/test_lead_imports_dedup.py` | created |

**9 files, no migration.** Inside rule-8 budget.

## Plan

1. Implement `parser.py`. Uses `csv.DictReader` for CSV (sniffing dialect) and `openpyxl` for XLSX. Yields `ParsedRow(row_number, raw, mapped)` where `mapped` is a `dict[crm_field_key, raw_value]`.
2. Implement `dedup.py`. Normalize phone via `re.sub(r"\D", "", s)`; email via `s.strip().lower()`. Lookup uses an indexed query on `leads.contact.phone_normalized` + `leads.contact.email_lower` (these columns are assumed to exist on `contacts` from Phase 2.4; if they don't, the migration in Step 1 adds them — but we should verify first; if missing, add them in this step's migration addendum).
3. Wire `service.commit_mapping`: validate mapping shape (every key exists in CSV header from the stored file's first line; every value is either `null` or a known target from `available_targets()`), reject mappings touching `id`/`org_id`/`source`/`created_at`/`updated_at`. Persist mapping JSONB, transition status, enqueue task.
4. Implement the Celery task:
   - Load `LeadImport`, set status `processing`.
   - Iterate parser. For each row, try to build a `LeadCreate` from the mapped values + `source='bulk_import'`.
   - Dedup check → if match, increment `duplicates_skipped`, continue.
   - Else, in a SAVEPOINT, call `LeadService.create(...)`. On exception, increment `errors`, append `{row_number, raw, error}` to error list, continue.
   - At end, write error CSV, update `counts` + `status='completed'` + `error_report_path`.
   - Emit `lead.import.completed` audit event.
5. Idempotency: at task start, check status. If already in `completed`/`failed`/`cancelled`, return immediately (no-op).
6. Stream-errors endpoint reads the error CSV from disk and returns as `text/csv` with `Content-Disposition: attachment`.
7. Tests.

## Tests

`api/tests/test_lead_imports_process.py`:

- **Happy path:** upload a 10-row CSV, commit mapping, run Celery task synchronously (via `task.apply()`). Verify `status='completed'`, `counts={'imported': 10, ...}`, 10 new leads exist with `source='bulk_import'`.
- **Mixed batch:** 10 rows — 7 good, 2 dup (against pre-seeded leads), 1 invalid (bad email). Verify `counts={'imported': 7, 'duplicates_skipped': 2, 'errors': 1}`. Error CSV contains the bad row with the validation error message.
- **Mapping rejects system fields:** commit with `mapping={"Email": "id"}` → 422.
- **Mapping rejects unknown custom field:** commit with `mapping={"X": "custom_data.unknown_key"}` → 422 with "create custom field first".
- **Status transitions:** invalid transition (commit on `completed`) → 409.
- **Cancel:** cancel on `awaiting_mapping` → `status='cancelled'`. Cancel on `completed` → 409.
- **Idempotent re-run:** run task twice on the same import — second run is a no-op (counts don't double).
- **Audit:** one `lead.import.completed` event per import; per-row `lead.created` count matches `counts.imported`.

`api/tests/test_lead_imports_dedup.py`:

- `normalize_phone("+91 98765-43210") == "919876543210"`.
- `normalize_phone("9876543210") == "9876543210"`.
- `lowercase_email(" Asha@Example.com ") == "asha@example.com"`.
- `find_existing` matches on phone match alone; on email match alone; not on neither.

## Smoke

```powershell
# Trigger end-to-end via the API (assumes Celery worker running)
$token = "<owner JWT>"
$upload = curl -X POST http://localhost:8000/api/v1/leads/import/upload `
  -H "Authorization: Bearer $token" `
  -F "file=@tests/fixtures/zoho-sample-10.csv" `
  -F "source_platform=zoho" -F "name=Smoke"
$id = ($upload | ConvertFrom-Json).id

curl -X POST "http://localhost:8000/api/v1/leads/import/$id/commit" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"mapping": {"Full Name":"contact.full_name","Email":"contact.email","Phone":"contact.phone","Notes":"notes"}}'

# Wait a moment, then poll
curl "http://localhost:8000/api/v1/leads/import/$id" -H "Authorization: Bearer $token"
# Expect status=completed, counts={imported:..., duplicates_skipped:..., errors:...}
```

## Risks

- **`contacts` table normalized fields:** dedup needs `phone_normalized` and `email_lower` indexed columns on the contacts table. If Phase 2.4 already added them, great; if not, this step's hidden cost is a small migration to add them with a backfill. **Implementer checks first** — if the columns are missing, file the migration as a sibling to this step or roll into Step 1's migration and document.
- **Celery task timeout on 50k rows:** local PG should comfortably handle 50k inserts in under a minute. Set a generous task soft timeout (5 min) and hard timeout (10 min). If a real import hits the hard timeout, the chunked-subtask follow-on lands.
- **`LeadService.create()` signature today** may not accept an explicit `actor_user_id` override (it likely reads from request context). The bulk-import path has no request context — pass it explicitly. **Implementer extends the service signature in this step** if needed (additive, non-breaking).
- **Error CSV column order:** match the source CSV column order + append two trailing columns `__row_number` + `__error`. Reps re-use the error CSV to fix and re-upload; preserving original column order lets them edit in place.

## Rollback

Cancel the Celery task if running. Revert the .py files. The `lead_imports` table from Step 1 remains; rows already in `completed` keep their counts but lose their commit path. New uploads are still possible from Step 1 but cannot commit.
