# Step 10 — Catalog CSV import — validation + errors.csv

**Goal:** Bring the catalog bulk-import surface up to the same level as leads / contacts — wire shared validators into per-row processing, and add a downloadable `errors.csv` endpoint so operators can see exactly which SKUs were rejected and why.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** COMPLETED — service-side validators (SKU pattern, name shape via `validate_name`, ISO 4217 currency, price upper bound) wired into `bulk_import_items` row loop via new `_validate_bulk_import_row` helper; failures land in the response `errors[]` with `{row_index, sku, column, value, reason}`. Frontend gained a "Download errors CSV" button that composes the CSV client-side (catalog import is synchronous, so the browser still holds the parsed rows). Error table now shows Column + Value columns. **Went with Option B (no persistence table)** — see Notes. No migration. Backend parse-check clean; frontend tsc + eslint + prettier all clean.
**Depends on:** Step 1 (`validators.py` + `import_errors.py`), Step 8 (contacts pattern is the template).

---

## Scope

Backend service + one new endpoint + frontend button + display. Frontend currently has a client-side CSV parser + row validation; the parity gain here is the *server-side* consistency + downloadable error report.

Files:

- `api/src/app/core/catalog/service.py` — `bulk_import_items()` (around lines 546–638)
- `api/src/app/core/catalog/router.py` — new `errors.csv` route
- `api/src/app/core/catalog/data_access.py` — new `get_bulk_import_errors` reader (may need a small `tbl_catalog_import_runs` table if none exists; confirm during kickoff)
- `api/alembic/versions/00XX_catalog_import_runs.py` — created if no run-tracking table exists
- `api/tests/test_catalog_import_validation.py` — new
- `app/src/app/features/user/core/catalog/import/bulk-import.page.ts` + `.html` — download button + extended error rows
- `app/src/app/features/user/core/catalog/catalog-api.service.ts` — new download method

## Backend changes

### Service — `bulk_import_items(...)`

The current row loop (around service.py:546) validates: `sku` non-empty, `name` non-empty, `price` numeric, `cost_price` optional-non-negative, `currency` optional, `tags` split/dedup. It doesn't validate `sku` shape, `name` content, or `currency` code.

Add:

```python
from api.src.app.shared.validators import (
    validate_name, ValidationError,  # for the name field
)
from api.src.app.shared import import_errors

# … in row loop:
# SKU shape: uppercase alphanumeric + '-' + '_', 2–64 chars.
if not SKU_RE.match(sku):
    errors.append(import_errors.ImportError(
        row_number=idx + 1, column="sku", value=sku,
        reason="SKU must be 2–64 chars, uppercase alphanumeric + '-' or '_'",
    ))
    continue

# Name content:
try:
    name = validate_name(row["name"])
except ValidationError as e:
    errors.append(import_errors.ImportError(... reason=e.reason ...))
    continue

# Currency: ISO 4217 3-letter uppercase.
if currency and not CURRENCY_RE.match(currency):
    errors.append(import_errors.ImportError(
        row_number=idx + 1, column="currency", value=currency,
        reason="currency must be a 3-letter ISO 4217 code (e.g. INR, USD)",
    ))
    continue

# Price: already numeric-checked. Add range 0 ≤ price ≤ 1e9.
if price < 0 or price > 1_000_000_000:
    errors.append(import_errors.ImportError(... reason="price out of range 0–1,000,000,000" ...))
    continue
```

Constants added at the top of the service module:

```python
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
```

Rows that fail validation are collected into `errors[]` and, on commit, persisted alongside the run for later download.

### Persisting errors for later download

Catalog imports don't currently have a run-tracking table. Two options — pick during kickoff:

- **Option A (preferred):** add `tbl_catalog_import_runs` with `id`, `org_id`, `created_by`, `created_at`, `total_rows`, `inserted`, `skipped`, `errors_json`, `original_file_bytes`. Persist errors + original file for the `errors.csv` endpoint to read back.
- **Option B (light):** skip persistence; the `errors.csv` endpoint takes the file re-uploaded via a stateless POST. Simpler DB story but forces the operator to re-upload to see the error report.

Option A matches leads / contacts. Confirm during kickoff.

### Router — new endpoint

```python
@router.get("/bulk-import/{run_id}/errors.csv", response_class=StreamingResponse)
def download_bulk_import_errors(run_id: UUID, db: DbSession, ctx: AuthContext = Depends(...)):
    return service.build_bulk_import_errors_csv_response(db, run_id, ctx.org_id)
```

### Service builds the response

Loads the persisted run's `errors_json` + original headers, passes into `shared.import_errors.write_errors_csv(...)`, streams the response with attachment disposition.

### DAL — pure reader

```python
def get_bulk_import_run(db, run_id, org_id) -> CatalogImportRun | None: ...
```

## Frontend changes

`bulk-import.page.ts` currently runs its own client-side validation and shows inline errors. After Option A lands, add:

- A "Download errors CSV" button on the result screen, visible when `errors.length > 0`.
- Wire to a new `catalogApi.downloadBulkImportErrors(runId): Observable<Blob>` method.
- Extend the inline errors list to display `column` and `value` alongside `reason`.

The upload/dry-run/commit flow itself is unchanged — same three phases, same buttons.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/catalog/service.py` | modified — row-level validation + response builder |
| `api/src/app/core/catalog/router.py` | modified — new `errors.csv` route |
| `api/src/app/core/catalog/data_access.py` | modified — `get_bulk_import_run` reader (+ any inserts moved through DAL) |
| `api/src/app/core/catalog/models.py` | modified — new `CatalogImportRun` model (Option A) |
| `api/src/app/core/catalog/schemas.py` | modified — response schemas |
| `api/alembic/versions/00XX_catalog_import_runs.py` | created (Option A) |
| `api/tests/test_catalog_import_validation.py` | created |
| `app/src/app/features/user/core/catalog/import/bulk-import.page.ts` | modified — download button + method wiring |
| `app/src/app/features/user/core/catalog/import/bulk-import.page.html` | modified — download button + error columns |
| `app/src/app/features/user/core/catalog/catalog-api.service.ts` | modified — new download method |

**~10 files + 1 migration.** At the ceiling.

## Tests

`api/tests/test_catalog_import_validation.py`:

- Upload a CSV with rows exercising each validator failure mode: bad SKU (`"abc/def"`), name with emoji, currency `"INR2"`, price -5, and a valid row.
- Assert dry-run response reports 4 errors with correct columns + values + reasons; 1 will_insert.
- Assert commit persists 1 catalog item and stores 4 errors on the run.
- `GET /bulk-import/{run_id}/errors.csv` returns a text/csv payload with the correct columns.
- Regression: existing duplicate-SKU behavior still skips and counts correctly.

## Smoke

```
docker exec crm_api-api-1 pytest tests/test_catalog_import_validation.py -v

# Manual walk against Ajay's Workspace:
# 1. Prepare a CSV:
#    sku,name,price,currency
#    SOFA-01,Blue Sofa,29999,INR
#    abc/def,Broken SKU,5000,INR
#    SOFA-02,😀 Emoji Name,1000,INR
#    SOFA-03,Fine Name,-5,INR
#    SOFA-04,Fine Name,1000,ZZZ
# 2. /user/settings/catalog → Bulk import → upload the CSV.
# 3. Preview: shows 1 will_insert, 4 errors with column + value visible.
# 4. Commit → 1 item created.
# 5. Click "Download errors CSV" → file downloads with the 4 rows + reasons.
```

## Risks

- **Option A adds a table** — the new `tbl_catalog_import_runs` matches the tenant-scoped `tbl_` convention with `org_id` + RLS. Small, low-risk addition; migration is single-table.
- **Existing catalog imports have no history** — operators lose no data (there was no history to lose). Old dry-runs were ephemeral.
- **SKU regex strictness** — `^[A-Z0-9][A-Z0-9_\-]{1,63}$` blocks lowercase and non-alphanumeric characters other than `-` and `_`. If an existing catalog uses `/` or `.` in SKUs, this is a break. Confirm during kickoff; if needed, broaden to `[A-Z0-9./_\-]`.

## Rollback

Revert the source files; downgrade the migration. Existing catalog rows are untouched (SKU column and constraints in `tbl_catalog_items` unchanged).

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: `tbl_catalog_import_runs` (new) has `org_id` + RLS from creation. Follows the `tbl_` naming convention.
- ✅ Rule 3: Catalog items have `custom_data` JSONB (existing); custom-field values in the CSV route through the dynamic-form validator path (Step 1-tightened).
- ✅ Rule 4: Not a form-render concern.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions — reuses the existing `catalog.write` key. No new permission.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 10 files + 1 migration, at the ceiling.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs. Option A vs Option B decided at kickoff, not deferred.

## Layered-architecture self-check

- Router → Service → DAL preserved. New endpoint calls service; service composes and calls DAL; DAL is pure CRUD. ✅
- Service is the only layer that calls `db.commit()`. ✅
- Bulk-import service, if it currently performs any direct SQL (per the DAL-backfill notes about catalog being on the exception list), gets its new writes routed through DAL functions as part of this step — no new violations added. ✅

## After this track

- All three CSV imports (contacts, leads, catalog) produce byte-identical `errors.csv` output through the single `shared.import_errors.write_errors_csv` writer.
- Every form in the app validates against the same regex the CSV imports use — one edit to `shared/validators.py` (with the FE sync test) changes the rule everywhere.
- Support tickets like "why did my import skip these rows" are answered by the operator downloading the errors CSV themselves.
