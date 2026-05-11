# Step 2.4 — Contacts: backend

**Goal:** `contacts` table with `custom_data` JSONB + GIN index, CRUD endpoints, bulk search/filter that supports custom-field queries. Pre-seed system custom field defs for `contact`.
**Phase:** 2
**Depends on:** 2.1, 1.4
**Status:** Pending

## Scope
**In-scope:**
- Model `Contact` (TenantScoped): id, org_id, full_name, phone, email, source, tags (text[]), notes, custom_data JSONB, created_at, updated_at.
- Migration with GIN index on `custom_data` and `tags`. Indexes on `(org_id, phone)`, `(org_id, email)`, `(org_id, full_name trigram)` for search.
- Schemas: `ContactCreate`, `ContactUpdate`, `ContactOut`, `ContactListItem`.
- CRUD `/api/v1/contacts`: list (paginated, filters: q, source, tag, custom_data filters via `custom.<key>=value`), get, create, update, delete.
- Service ensures `custom_data` keys match defined fields (validates via `custom_field_definitions` for entity_type=`contact`).
- Permission keys: `contacts.read`, `contacts.write`.
- Module descriptor exported (sidebar: "Contacts", icon, route `/contacts`).
- Seed: system custom field defs for contact (e.g., `dob` date optional).

**Out of scope:**
- Frontend — 2.5.
- Activities/notes integration — 2.6/2.7.

## Files to touch
- `api/src/app/core/contacts/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0007_contacts.py` (created)
- `api/src/app/main.py` (modified — register router)
- `api/src/app/scripts/seed_contact_system_fields.py` (created)

## Plan
1. Model + migration. Use `pg_trgm` for fuzzy `full_name` search (`CREATE EXTENSION IF NOT EXISTS pg_trgm`).
2. Schemas with `custom_data` typed loosely as `dict[str, Any]`.
3. Service: list with filters (build SQLAlchemy where clauses dynamically). Custom-data filter: `custom.budget_range=premium` → `custom_data ->> 'budget_range' = 'premium'`.
4. Validation hook on create/update: load field defs for `contact`, ensure no unknown keys, ensure types match (with coercion).
5. Endpoints + permission gates.
6. Seed system fields; print SQL.

## DB changes / migrations
- `0007_contacts`: table + RLS + GIN index on custom_data + GIN trigram on full_name + indexes.

## Tests to add
- `tests/test_contacts_crud.py` — CRUD, RLS isolation, custom-data validation rejects unknown keys.
- `tests/test_contacts_search.py` — search by name, by tag, by custom field.

## Verification checklist
**Backend:**
- run: `uv run alembic upgrade head` → 0007 applied.
- run: `python -m src.app.scripts.seed_contact_system_fields` → 1 row inserted.
- hit: `POST /contacts` with `custom_data={"dob":"1990-05-01"}` → 201.
- hit: `GET /contacts?q=John&custom.budget_range=premium` → filtered.

## Self-check (10 rules)
- [ ] org_id + RLS + GIN on custom_data.
- [ ] No imports from packs.
- [ ] No hardcoded contact fields beyond core columns; everything else flows through custom_data.

## Stop & report
Await "proceed" before Step 2.5.
