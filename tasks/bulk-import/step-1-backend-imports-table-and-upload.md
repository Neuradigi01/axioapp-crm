# Step 1 — Backend: `lead_imports` table + upload endpoint

**Goal:** Create the `lead_imports` job table, the file-storage layout under `./storage/{org_id}/imports/{import_id}/`, the `POST /api/v1/leads/import/upload` multipart endpoint, and the `leads.import` permission key. The endpoint stores the raw file + creates a job row in state `awaiting_mapping`. No parsing yet — Step 2 does that.
**Track:** Bulk Import
**Status:** Pending
**Depends on:** Manual Lead Entry Step 1 (the `lead.source` enum), Phase 1.5 (permissions + audit), Phase 1.7 (audit log).

---

## Scope

In-scope:

- Alembic migration adding `lead_imports` table + `lead_import_status_enum` PG type.
- SQLAlchemy `LeadImport` model + Pydantic schemas for create/read/list.
- `POST /api/v1/leads/import/upload` — accepts multipart `file` + form fields `source_platform` (string from a fixed enum) + optional `name` (user label). Returns the new `LeadImport` row.
- File saved to disk via the existing `StorageBackend` at `./storage/{org_id}/imports/{import_id}/source.{csv|xlsx}`.
- File-type validation (mimetype + extension), file-size cap (10 MB), row-count cap (50,000 lines for CSV — line-count check only, not full parse).
- New permission key `leads.import`, granted by default to `owner` + `admin` role templates.
- Audit event `lead.import.started` emitted on successful upload (payload: `{import_id, source_platform, filename, byte_size, row_count_estimate}`).
- Tests covering: happy path, oversized file rejection, bad mimetype rejection, RLS isolation (org A can't list org B's imports), permission gate (Employee gets 403).

Out of scope:

- No parsing, validation, mapping, dedup, commit, or Celery — all in Step 2.
- No mapping presets — Step 3.
- No frontend — Steps 4–6.

## The `lead_imports` table

```sql
CREATE TYPE lead_import_status_enum AS ENUM (
    'awaiting_mapping',   -- file uploaded, user has not yet committed mapping
    'mapping_committed',  -- mapping saved, Celery job queued
    'processing',         -- Celery worker actively parsing/inserting
    'completed',          -- terminal: rows landed (with optional per-row errors)
    'failed',             -- terminal: catastrophic failure (file unreadable, etc.)
    'cancelled'           -- terminal: user cancelled before completion
);

CREATE TABLE lead_imports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    uploaded_by     UUID NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,             -- e.g. "Zoho export 2026-05-22"
    source_platform TEXT NOT NULL,             -- 'zoho' | 'hubspot' | 'salesforce' | 'freshsales' | 'generic_csv' | 'custom'
    original_filename TEXT NOT NULL,
    storage_path    TEXT NOT NULL,             -- './storage/{org_id}/imports/{id}/source.csv'
    byte_size       BIGINT NOT NULL,
    row_count_estimate INT NOT NULL,           -- line count - 1 (header)
    mime_type       TEXT NOT NULL,
    status          lead_import_status_enum NOT NULL DEFAULT 'awaiting_mapping',
    mapping         JSONB,                     -- filled in by mapping-commit (Step 2/3)
    counts          JSONB,                     -- {imported, duplicates_skipped, errors} filled by job
    error_report_path TEXT,                    -- ./storage/{org_id}/imports/{id}/errors.csv after job
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX lead_imports_org_status_idx ON lead_imports (org_id, status, created_at DESC);

-- RLS: standard org_id policy, mirrored from existing tables
ALTER TABLE lead_imports ENABLE ROW LEVEL SECURITY;
CREATE POLICY lead_imports_tenant_isolation ON lead_imports
    USING (org_id = current_setting('app.org_id', true)::uuid);
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_lead_imports.py` | created |
| `api/src/app/core/leads/imports/__init__.py` | created |
| `api/src/app/core/leads/imports/models.py` | created — `LeadImport`, `LeadImportStatus` |
| `api/src/app/core/leads/imports/schemas.py` | created — `LeadImportCreate`, `LeadImportRead`, `LeadImportList`, `SourcePlatform` literal |
| `api/src/app/core/leads/imports/service.py` | created — `upload(file, source_platform, name, uploader)` |
| `api/src/app/core/leads/imports/router.py` | created — `POST /leads/import/upload`, `GET /leads/import` (list), `GET /leads/import/{id}` |
| `api/src/app/core/leads/__init__.py` | modified — include the new subrouter |
| `api/src/app/core/permissions/registry.py` | modified — register `leads.import` key + grant to Owner/Admin |
| `api/src/app/core/audit/events.py` | modified — declare `LEAD_IMPORT_STARTED` |
| `api/tests/test_lead_imports_upload.py` | created |

**10 files, 1 migration.** At rule-8 ceiling — split was considered but the new sub-package is one logical unit; splitting would scatter the model/schema/service across two steps unnaturally.

## Plan

1. Create the migration + run upgrade/downgrade locally to confirm clean.
2. Build the SQLAlchemy model + Pydantic schemas. `SourcePlatform` is a Literal string in `schemas.py` (Python enum overkill for six values; the registry of platform-specific knowledge lives in Step 3's presets table).
3. Implement `service.upload()`:
   - Validate mimetype against `{text/csv, application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet}`.
   - Validate byte_size ≤ 10 MB. Reject with 413 otherwise.
   - For CSV: stream-count newlines (without fully parsing) to estimate row count; reject if > 50,000.
   - For XLSX: open with `openpyxl` in read-only mode, count rows in the first sheet; reject if > 50,000.
   - Generate import id, write file via `storage_backend.put(...)` to `./storage/{org_id}/imports/{import_id}/source.{ext}`.
   - Insert the `LeadImport` row in `awaiting_mapping`.
   - Emit `lead.import.started` audit event.
4. Wire the router. Reuse the existing `Depends(require_permission("leads.import"))` dependency.
5. Register the permission key in `core/permissions/registry.py`. Add it to Owner (via `ALL_KEYS` sentinel) and Admin (explicit append).
6. Tests.

## Tests

`api/tests/test_lead_imports_upload.py`:

- **Happy path:** upload a 100-row valid CSV → 201 with `status='awaiting_mapping'`, file exists on disk at the expected path, `row_count_estimate==100`.
- **Audit event:** the response correlates with a `lead.import.started` audit row.
- **Oversize:** upload an 11 MB file → 413.
- **Row-cap:** upload a 60,000-row CSV → 422 with a clear error.
- **Bad mimetype:** upload a `.pdf` → 415.
- **RLS isolation:** create import in org A as Owner_A. As Owner_B, `GET /leads/import/{id}` → 404 (not 403 — leak-resistant).
- **Permission gate:** as Employee (no `leads.import`), upload returns 403.
- **`updated_at` advance:** create + verify `created_at == updated_at` initially.

## Smoke

```powershell
# Migrations clean
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run alembic downgrade -1
docker exec template_api-api-1 uv run alembic upgrade head

# Tests
docker exec template_api-api-1 uv run pytest tests/test_lead_imports_upload.py -v

# Manual upload (curl)
curl -X POST http://localhost:8000/api/v1/leads/import/upload `
  -H "Authorization: Bearer $token" `
  -F "file=@sample-zoho-export.csv" `
  -F "source_platform=zoho" `
  -F "name=Zoho smoke test"
# Expect 201 with status='awaiting_mapping' and a storage_path under ./storage/...
```

## Risks

- **Row count for XLSX is expensive on a 50k-row file** — opening with openpyxl read-only mode is fine, but if it becomes slow, defer the row-count check to Step 2's Celery job and accept whatever the upload step gives us (skip the row-cap gate for XLSX). Trade-off is small; CSV is the dominant case.
- **Source-platform list lives in two places** (schema literal + Step 3's presets table) — that's intentional. Schema literal is the API contract; presets table is data. They stay in sync because Step 3's seed migration writes one row per known platform.
- **Storage path collision** in a re-upload scenario — each upload gets a fresh UUID for import_id, so paths never collide.
- **`./storage/` outside container** — confirm the volume mount in `docker-compose.yml` covers the imports subdir. Should already be wrapped under the existing `./storage` mount.

## Rollback

`alembic downgrade -1` removes the table and enum. Delete the new files. Revert the permission registry edit. Storage files are not cleaned (intentional — leave orphans for now, the eventual cleanup task is a separate concern).
