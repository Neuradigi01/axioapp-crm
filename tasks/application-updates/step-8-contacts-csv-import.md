# Step 8 — Contacts CSV import — validation + errors.csv

**Goal:** Wire the shared backend validators (Step 1) into the contacts-import service so every row is checked for email / phone / name shape before write, and add a downloadable `errors.csv` endpoint that matches the leads-import schema — row-numbered, column-tagged, human-readable reasons.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** Pending
**Depends on:** Step 1 (`validators.py` + `import_errors.py`).

---

## Scope

Backend service + one new endpoint + frontend button + display. No DB schema changes.

- Backend service that runs validation inline during dry-run and commit.
- New endpoint `GET /api/v1/contacts/imports/{id}/errors.csv` producing a downloadable CSV with `__row_number`, `__column`, `__value`, `__error_reason` columns appended to the original file columns.
- Frontend button on the import-result screen to fetch and download that file.
- The dry-run preview already exposes an in-memory `errors[]` list — extend it to include the new validation reasons (not just "missing required field" + "duplicate phone").

## Backend changes

### Service — `api/src/app/core/contacts/imports/service.py`

Inside the per-row processing loop (both dry-run path around lines 202–204 and commit path around lines 296–299), add:

```python
from api.src.app.shared.validators import (
    validate_email, validate_phone, validate_name, ValidationError,
)
from api.src.app.shared import import_errors

# … inside the row loop, after existing required-field check:
try:
    full_name = validate_name(row["full_name"])
except ValidationError as e:
    row_errors.append(import_errors.ImportError(
        row_number=idx + 1, column="full_name", value=row["full_name"], reason=e.reason,
    ))
    continue

if row.get("email"):
    try:
        email = validate_email(row["email"])
    except ValidationError as e:
        row_errors.append(import_errors.ImportError(
            row_number=idx + 1, column="email", value=row["email"], reason=e.reason,
        ))
        continue

if row.get("phone"):
    try:
        phone = validate_phone(row["phone"])
    except ValidationError as e:
        row_errors.append(import_errors.ImportError(
            row_number=idx + 1, column="phone", value=row["phone"], reason=e.reason,
        ))
        continue
```

Rows that fail validation are **not** written; they land in the `row_errors` collection alongside the existing "missing full_name" and "duplicate phone" errors.

Persist `row_errors` on the import row (existing `contact_imports.errors` JSON column, or add if not present — confirm during kickoff). This is what the `errors.csv` endpoint reads back.

### DAL — `api/src/app/core/contacts/imports/data_access.py`

Add:

```python
def get_import_errors(db, import_id, org_id) -> list[dict]:
    """Load persisted per-row errors for the import."""
```

Pure read; no transaction. Router → Service → DAL discipline preserved.

### Router — `api/src/app/core/contacts/imports/router.py`

New endpoint (after the existing `/commit` route):

```python
@router.get("/{import_id}/errors.csv", response_class=StreamingResponse)
def download_errors_csv(
    import_id: UUID,
    db: DbSession,
    ctx: AuthContext = Depends(...),
):
    return service.build_errors_csv_response(db, import_id, ctx.org_id)
```

### Service builds the response

Loads the original headers + rows via the existing parser (or from the persisted error rows), passes into `shared.import_errors.write_errors_csv(...)`, returns a `StreamingResponse` with `Content-Type: text/csv` + `Content-Disposition: attachment; filename=<import_id>_errors.csv`.

### Reason strings (used verbatim in `errors.csv` and in dry-run preview)

- `"required field missing"` — `full_name` absent
- `"name contains disallowed characters"` — regex fail
- `"invalid email format"`
- `"phone must be 8–15 digits (with optional country code)"`
- `"duplicate in file"` — same phone / email twice in the upload
- `"duplicate of existing contact"` — matches a row already in DB

## Frontend changes

### Import wizard result screen — `app/src/app/features/user/core/contacts/imports/import-wizard.page.ts` + `.html`

- Add a `Download errors CSV` button to the result screen, visible when `errorCount > 0`.
- Wire it to a new API-service method `contactsApi.downloadImportErrors(importId): Observable<Blob>` — `GET /api/v1/contacts/imports/{id}/errors.csv` with `responseType: 'blob'`.
- Trigger the browser download with a synthesized `<a download="…">` click.
- The existing dry-run preview list already shows `{row, reason}` — extend to also render the offending `column` + `value` for the new error types, so users see *what* was wrong before downloading anything.

### API service — `app/src/app/features/user/core/contacts/contacts-api.service.ts`

Add the `downloadImportErrors(importId)` method.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/contacts/imports/service.py` | modified — row-level validation + response builder |
| `api/src/app/core/contacts/imports/data_access.py` | modified — `get_import_errors` |
| `api/src/app/core/contacts/imports/router.py` | modified — new `errors.csv` route |
| `api/src/app/core/contacts/imports/schemas.py` | modified — extend dry-run response with `column` + `value` fields on each error |
| `api/src/app/core/contacts/imports/models.py` | possibly modified — add `errors JSONB` column if not already present |
| `api/alembic/versions/00XX_contact_imports_errors_column.py` | created only if the column doesn't exist |
| `api/tests/test_contact_imports_validation.py` | created |
| `app/src/app/features/user/core/contacts/imports/import-wizard.page.ts` | modified — download button + method |
| `app/src/app/features/user/core/contacts/imports/import-wizard.page.html` | modified — download button + extended error rows |
| `app/src/app/features/user/core/contacts/contacts-api.service.ts` | modified — new download method |

**~9–10 files + 0–1 migrations.** Within the per-step rule.

## Tests

`api/tests/test_contact_imports_validation.py`:

- Upload a CSV with 5 rows: 1 valid, 1 missing full_name, 1 name = `"😀😀"`, 1 email = `"bad@"`, 1 phone = `"abc"`.
- Dry-run response: `will_insert=1`, `will_skip=4`, errors list has 4 entries with correct `row`, `column`, `value`, `reason`.
- Commit: only the valid row lands in `tbl_contacts`; the persisted `errors` field carries the 4 error records.
- `GET /errors.csv` returns a text/csv payload with headers `full_name,phone,email,__row_number,__column,__value,__error_reason` and 4 error rows.
- Regression: the existing "duplicate phone" and "missing full_name" cases still fire and appear in the same errors CSV.

## Smoke

```
docker exec crm_api-api-1 pytest tests/test_contact_imports_validation.py -v

# Manual walk against Ajay's Workspace:
# 1. Prepare a small CSV:
#    full_name,phone,email
#    John Doe,9876543210,john@example.com
#    ,9876543211,alice@example.com
#    😀😀😀,9876543212,bad@example.com
#    Bob Smith,abc,bob@example.com
#    Carol Jones,9876543213,test@
# 2. /user/contacts → Import → upload the CSV.
# 3. Dry-run screen: shows 1 will_insert, 4 errors with column + value visible.
# 4. Click "Commit" → 1 contact created.
# 5. Click "Download errors CSV" → file downloads with the 4 rows + reasons.
```

## Risks

- **Existing dry-run response shape** — the schema change (adding `column` and `value` to each error entry) is backward-compatible for consumers that ignore extra fields, but the existing frontend template must be extended to display them. Called out above.
- **Large error volume** — the persisted `errors` JSON could grow if the file has 10 000 rows and 9 000 fail. Cap at 5 000 stored errors; the CSV response still runs the full pass and streams everything (memory-safe via `StreamingResponse`).
- **Column detection** — the CSV parser assigns columns like `column_2` when headers are blank. The `__column` in the error record uses the operator's mapping target when available, falling back to the raw header. Preserved in the reason so users can locate the offending column.

## Rollback

Revert the source files. Migration (if created) is a single-column add — safe to downgrade.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. Import lives in `core/contacts/imports/`.
- ✅ Rule 2: `tbl_contact_imports` (existing) has `org_id` and RLS — unchanged. Any new column carries no cross-tenant concern.
- ✅ Rule 3: Custom-field values in the CSV route through the existing dynamic-form validator path (already Step 1-tightened).
- ✅ Rule 4: Not a form-render concern.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 9–10 files, small changes each.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs. `errors.csv` shape is the final contract, not a placeholder.

## Layered-architecture self-check

- Router calls `service.build_errors_csv_response(...)`, never DB directly. ✅
- Service composes the response, calls DAL for reads, calls `shared.import_errors.write_errors_csv(...)`. ✅
- DAL is pure CRUD — no commits, flushes, or refreshes in this step. ✅
