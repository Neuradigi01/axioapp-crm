# Step 2.1 — Custom Fields engine: backend

**Goal:** Build the `custom_field_definitions` table, model, schemas, and CRUD endpoints scoped by `entity_type`. Enforce source rules (`system`/`pack`/`user`) in the service layer.
**Phase:** 2
**Depends on:** 1.5, 1.6, 1.8
**Status:** Pending

## Scope
**In-scope:**
- Model `CustomFieldDefinition`: id, org_id, entity_type, field_key, field_label, field_type (enum: text, number, select, multiselect, date, datetime, boolean, phone, email, currency), options (JSONB), is_required, is_hidden, display_order, source (enum: system, pack, user), pack_id (nullable), validation (JSONB), created_at, updated_at. `TenantScoped`.
- Migration with unique `(org_id, entity_type, field_key)` and index `(org_id, entity_type, is_hidden, display_order)`.
- Schemas: Create/Update/Out. Field-key validation: `^[a-z][a-z0-9_]{1,49}$`.
- Service rules:
  - `system` fields: created only by core seed, cannot be deleted, label/order/required editable; `field_key` immutable.
  - `pack` fields: created only by pack installer, cannot be deleted, label/order/hidden editable; `field_key` immutable.
  - `user` fields: full CRUD by users with `custom_fields.write`.
- CRUD endpoints under `/api/v1/custom-fields`:
  - `GET /custom-fields?entity_type=...` (list visible + hidden if requested)
  - `POST /custom-fields` (creates user field)
  - `PATCH /custom-fields/{id}` (label, order, hidden, required, validation; respects source rules)
  - `DELETE /custom-fields/{id}` (only `source=user`)
  - `GET /custom-fields/{entity_type}/render` — returns ordered, non-hidden field list for forms.
- Permission registry: `custom_fields.read`, `custom_fields.write`.

**Out of scope:**
- Frontend UI — 2.2.
- Dynamic form component — 2.3.
- Seeding pack defaults — 4.2.

## Files to touch
- `api/src/app/core/custom_fields/{__init__,models,schemas,service,router,module}.py` (created)
- `api/src/app/core/permissions/service.py` (modified — register perms)
- `api/alembic/versions/0006_custom_field_definitions.py` (created)
- `api/src/app/main.py` (modified — register router)

## Plan
1. Define enums for `field_type` and `source` (Python enum + SQLAlchemy `ENUM` type).
2. Build the model + migration with the specified unique + indexes.
3. Schemas with strict field-key validator, options validation per field_type (e.g., `select` requires non-empty `options.choices`).
4. Service: enforce source rules on every write path; hooks for "before delete" raise on system/pack source.
5. Router with the five endpoints above; pagination + filters.
6. Register `core/custom_fields/module.py` exporting MODULE descriptor — but `menu_position=None` (no sidebar entry; it lives inside Settings).
7. Add the audit logs (`custom_fields.created`, `.updated`, `.deleted`).

## DB changes / migrations
- `0006_custom_field_definitions`: table + RLS + unique + indexes.

## Tests to add
- `tests/test_custom_fields_crud.py` — create/list/update/delete user fields.
- `tests/test_custom_fields_source_rules.py` — system/pack fields cannot be deleted; their `field_key` cannot be changed; user perms apply.
- `tests/test_custom_fields_render.py` — `/render` returns only non-hidden, ordered correctly.

## Verification checklist
**Backend:**
- run: `uv run alembic upgrade head` → 0006 applied.
- hit: `POST /api/v1/custom-fields` body=`{entity_type:"contact",field_key:"dob",field_label:"DOB",field_type:"date"}` → 201, `source="user"`.
- hit: trying to DELETE a system field → 403.
- run: `uv run pytest tests/test_custom_fields*.py -v` → green.

**Code review:**
- open `core/custom_fields/service.py` — note source rule enforcement is centralized, not duplicated in router.

## Self-check (10 rules)
- [ ] Rule 3 implemented: `custom_field_definitions.source` column drives behavior.
- [ ] org_id + RLS.
- [ ] Permissions registered, not hardcoded.

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 2.2.
