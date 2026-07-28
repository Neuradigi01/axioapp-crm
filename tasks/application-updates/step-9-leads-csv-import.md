# Step 9 — Leads CSV import — new validation rules

**Goal:** Layer the shared name / email / phone validators into the existing async leads-import Celery task so its already-shipped `errors.csv` / `skipped.csv` / `warnings.csv` outputs carry format-level failures alongside the existing "missing full_name" / "duplicate contact" / "unmatched pipeline stage" cases.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** Pending
**Depends on:** Step 1 (`validators.py` + `import_errors.py`).

---

## Scope

The leads import is the most mature of the three — it already runs asynchronously via Celery, already produces three downloadable CSVs (`errors`, `skipped`, `warnings`), and already writes bucketed `error_reasons` / `skipped_reasons` / `warning_reasons` counts to the import row. This step extends its per-row validation with the shared rules; no new endpoints are needed.

Files:

- `api/src/app/core/leads/imports/tasks.py` — Celery worker; row loop
- `api/src/app/core/leads/imports/service.py` — shared error-writer plumbing (optional)
- `api/src/app/core/leads/imports/schemas.py` — reason bucket enum, if used
- `api/tests/test_lead_imports_validation.py` — new
- `app/src/app/features/user/core/leads/import/import-result.component.*` — extend the error table to show `column` + `value` when present (frontend already displays reasons)

## Backend changes

### `tasks.py` — inside `process_lead_import(import_id)`

The task iterates over rows around lines 380–443. Add validation calls immediately after the existing `full_name`-present check:

```python
from api.src.app.shared.validators import (
    validate_email, validate_phone, validate_name, ValidationError,
)

# … in the row loop:
try:
    full_name = validate_name(row["contact.full_name"])
except ValidationError as e:
    errors.append({
        "__row_number": idx + 1,
        "__column": "contact.full_name",
        "__value": row["contact.full_name"],
        "__error_reason": e.reason,
    })
    error_reasons[e.reason] = error_reasons.get(e.reason, 0) + 1
    continue

if row.get("contact.email"):
    try:
        row["contact.email"] = validate_email(row["contact.email"])
    except ValidationError as e:
        errors.append({... e.reason ...})
        error_reasons[e.reason] = error_reasons.get(e.reason, 0) + 1
        continue

if row.get("contact.phone"):
    try:
        row["contact.phone"] = validate_phone(row["contact.phone"])
    except ValidationError as e:
        errors.append({... e.reason ...})
        error_reasons[e.reason] = error_reasons.get(e.reason, 0) + 1
        continue
```

The task already writes `errors.csv` at the end — the shape is already `original_columns + __row_number + __error_reason`. Extend it to also emit `__column` and `__value` so the operator can see *which* column failed. This is a superset (existing consumers ignore the new columns).

### Migrate `errors.csv` writer to `shared.import_errors.write_errors_csv`

The leads task currently has its own inline CSV writer. Swap it for the shared helper (`shared/import_errors.py` from Step 1) so all three imports produce byte-identical output. This is a small refactor and keeps the "single writer" invariant that Step 1 promised.

### Reason strings

Existing reason strings (kept):

- `"missing required field 'contact.full_name'"`
- `"unmatched pipeline stage '<val>' — fell back to default"` (warnings.csv)
- `"contact merged into open lead"` (skipped.csv)
- `"duplicate in file"` (skipped.csv)

New reason strings (added):

- `"invalid email format"`
- `"phone must be 8–15 digits (with optional country code)"`
- `"name contains disallowed characters"`

These match the Step 1 `REASON` constants exactly.

## Frontend changes

`app/src/app/features/user/core/leads/import/import-result.component.*`:

- The existing table renders `row_number` + `reason`. Extend to also show `column` and `value` when the payload includes them (the existing endpoint already returns row-level errors via a list route, or via the `errors.csv` download).
- Extend the reason-bucket badges (rendered from `error_reasons` on the import row) to include the three new keys.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/leads/imports/tasks.py` | modified — validation calls in row loop, swap CSV writer for shared helper |
| `api/src/app/core/leads/imports/service.py` | modified — remove inline error writer if it lives here (delegate to shared helper) |
| `api/src/app/core/leads/imports/schemas.py` | modified — extend error-row schema with `__column` + `__value` |
| `api/tests/test_lead_imports_validation.py` | created |
| `app/src/app/features/user/core/leads/import/import-result.component.ts` | modified — reason bucket labels |
| `app/src/app/features/user/core/leads/import/import-result.component.html` | modified — error-row columns |

**~6 files.** Well within budget.

## Tests

`api/tests/test_lead_imports_validation.py`:

- Upload a CSV with rows exercising each validator failure mode (bad email, bad phone, garbage name, plus a valid row).
- Run the Celery task synchronously (as the existing test harness does).
- Assert `errors.csv` includes one row per invalid input with correct `__column` + `__value` + `__error_reason`.
- Assert `error_reasons` bucket on the import row carries the three new keys with correct counts.
- Regression: existing `skipped.csv` (duplicates) and `warnings.csv` (unmatched pipeline stage) still fire correctly.

## Smoke

```
docker exec crm_api-api-1 pytest tests/test_lead_imports_validation.py -v

# Manual walk against Ajay's Workspace:
# 1. /user/leads → Import → upload a CSV with a bad-email row and a bad-phone row alongside valid rows.
# 2. Wait for the async task to complete (result page auto-refreshes).
# 3. Result page shows updated bucket badges: "invalid email format: 1", "phone must be 8–15 digits …: 1".
# 4. Click "Download errors.csv" → CSV contains the two rows with column + value + reason.
# 5. Existing test: an unmatched pipeline stage still lands in warnings.csv (regression check).
```

## Risks

- **Celery task backpressure** — validation adds negligible per-row cost (regex compile once, called cheaply). No impact expected on throughput.
- **Existing consumers of `errors.csv`** — if any downstream tool parses the CSV by column position (rather than header), adding `__column` and `__value` breaks it. All internal consumers use headers; the response is documented as "columns may extend, always parse by header." No known external consumer.
- **Shared writer swap** — the shared helper must produce byte-identical output for the columns that existed before. Verified by a golden-file test in `test_lead_imports_validation.py` (assert against a checked-in fixture CSV).

## Rollback

Revert the 6 files. `errors.csv` reverts to the pre-Step-9 shape (no `__column` / `__value`, no new reasons).

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: `tbl_lead_imports` (existing) has `org_id` + RLS; unchanged.
- ✅ Rule 3: Custom-field values in the CSV validate via the dynamic-form path (already Step 1-tightened).
- ✅ Rule 4: Not a form-render concern.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 6 files, contained changes.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs. Shared writer swap is completed here, not deferred.

## Layered-architecture self-check

- The Celery task is a documented helper module (per the DAL-backfill exception list — pre-existing before layered layout). Its per-row validation calls pure functions from `shared/validators.py`; no new SQL execution is added to the task. ✅
- If the swap to `shared.import_errors.write_errors_csv` requires any new DB read, it goes through `service.py` (existing) which delegates to `data_access.py` (existing). No new SQL in the task. ✅
