# Step 8 — Shared custom-data validation engine

**Goal:** Extract the `_load_field_defs() / _coerce_value() / _validate_custom_data()` trio duplicated near-verbatim in 5 services into one shared engine.
**Track:** Code Update — Audit & Validation
**Depends on:** none
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/custom_fields/validation.py` exposing `CustomDataValidator(session, org_id, entity_type)` with methods:
  - `async load() -> dict[str, FieldDef]`
  - `coerce(field_def, raw)` (delegates to Step 10's coercion module if that lands first)
  - `validate(payload: dict) -> dict` (returns coerced dict, raises 422 on errors)
- Migrate `contacts`, `leads`, `appointments`, `catalog`, `walk_ins` services to use it.

**Out of scope:**
- Definition CRUD (managed elsewhere by core/custom_fields).
- Pack-specific extensions (the engine handles `source` = system/pack/user identically).

## Files to touch
- `api/src/app/shared/custom_fields/__init__.py` (create)
- `api/src/app/shared/custom_fields/validation.py` (create)
- `api/src/app/core/contacts/service.py` (`:68-193` — delete and import)
- `api/src/app/core/leads/service.py` (`:126-235`)
- `api/src/app/core/appointments/service.py` (`:85-175`)
- `api/src/app/core/catalog/service.py`
- `api/src/app/core/walk_ins/service.py`
- `api/tests/shared/test_custom_fields_validation.py` (create)

## Plan
1. Move the implementation verbatim from `contacts/service.py` to the shared module (it's the most-developed copy).
2. Diff against the other 4 copies — pick up any unique branches (e.g. catalog-specific number formatting) and add as optional parameters.
3. Delete the 5 duplicated implementations.
4. Update each service's create/update path to instantiate `CustomDataValidator(session, org_id, entity_type)` and call `validate()`.
5. Confirm error messages stay identical (these surface as 422s to the frontend dynamic-form renderer).

## DB changes / migrations
None.

## Tests to add
- Unit: validate a `text` field — pass.
- Unit: validate a `select` field with invalid option — 422.
- Unit: validate a `number` field with string input — coerced.
- Integration: create contact with custom_data → validation runs end-to-end.

## Verification checklist
- `uv run pytest` — green.
- Browser smoke: open a contact form with custom fields, submit invalid data, confirm 422 error format unchanged.
- Cross-entity: same in a leads form.

## Self-check (10 rules)
- [ ] Engine works identically for `source=system/pack/user` field defs.
- [ ] No furniture-specific defaults in `shared/custom_fields/` (rule 3).
- [ ] No commented-out duplicate implementations.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
