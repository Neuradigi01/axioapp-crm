# Step 10 — Field-type coercion switch

**Goal:** Extract the `if field_type in (text, phone, email, select): ...` chain duplicated in 5 service files into one shared coercion module.
**Track:** Code Update — Audit & Validation
**Depends on:** Step 8 (validation engine calls this)
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/custom_fields/coercion.py` with a dispatch table `{FieldType.TEXT: coerce_text, FieldType.PHONE: coerce_phone, ...}` and `coerce_value(field_def, raw) -> Any`.
- Migrate the inlined switches.

**Out of scope:**
- Adding new field types (current set only).
- Localization of error messages (separate i18n track).

## Files to touch
- `api/src/app/shared/custom_fields/coercion.py` (create)
- `api/src/app/shared/custom_fields/validation.py` (use the dispatch table)
- `api/src/app/core/contacts/service.py` (remove inlined `_coerce_value` body)
- `api/src/app/core/leads/service.py`
- `api/src/app/core/appointments/service.py`
- `api/src/app/core/catalog/service.py`
- `api/src/app/core/walk_ins/service.py`
- `api/tests/shared/test_field_coercion.py` (create)

## Plan
1. Identify the field-type enum source (currently `app/core/custom_fields/`).
2. Build the dispatch table — one coercer per type.
3. Update `CustomDataValidator` (Step 8) to call `coerce_value()` from this module.
4. Delete inlined switches; if Step 8 already replaced the trio, this step just centralizes coercion further.

## DB changes / migrations
None.

## Tests to add
- One unit test per field type (text, number, phone, email, select, multi-select, date, boolean, json).
- Edge cases: empty string, null, wrong type.

## Verification checklist
- `uv run pytest tests/shared/test_field_coercion.py` — green.

## Self-check (10 rules)
- [ ] Dispatch table is the only place coercion logic lives.
- [ ] No furniture-specific types hardcoded.

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
