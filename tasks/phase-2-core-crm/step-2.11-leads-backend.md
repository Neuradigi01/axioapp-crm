# Step 2.11 — Leads: backend

**Goal:** `leads` table (FK to `contact`, `custom_data`), CRUD, stage move via pipeline engine, filters by stage/source/assigned_to.
**Phase:** 2
**Depends on:** 2.4, 2.9, 2.1
**Status:** Pending

## Scope
**In-scope:**
- Model `Lead` (TenantScoped): id, org_id, contact_id (FK→contacts), pipeline_stage (text — references `pipeline_stages.key` for the `leads` pipeline), status (active/won/lost), assigned_to_id (FK→users, nullable), budget Numeric, expected_close_date date, custom_data JSONB, created_at, updated_at.
- Migration + RLS + indexes (`org_id, pipeline_stage`, `assigned_to_id`).
- Endpoints `/api/v1/leads`: list (filters: stage, status, assigned_to, q, source via contact join, custom_data filters), get, create, update, delete, `POST /leads/{id}/move-stage`.
- Service uses `pipelines.move_card("leads", "leads", lead_id, to_stage)` (from 2.9).
- Permissions: `leads.read`, `leads.write`.
- Module descriptor (sidebar entry).

**Out of scope:**
- Frontend — 2.12.
- Auto-assign rules — later.

## Files to touch
- `api/src/app/core/leads/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0011_leads.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Model + migration; FK to contacts ON DELETE RESTRICT.
2. Validation: `pipeline_stage` must exist in stages of the `leads` pipeline.
3. `custom_data` validation against contact-or-lead field defs (entity_type `lead`).
4. Endpoints with rich filters; pagination cursor-based for performance.
5. Move-stage: writes audit log + activity (`status_change`).

## Tests to add
- `tests/test_leads_crud.py`
- `tests/test_leads_move_stage.py` — invalid stage rejected; valid move writes audit + activity.

## Verification checklist
**Backend:**
- after pack installer (4.2), `POST /leads` succeeds with stage `new`.
- `POST /leads/{id}/move-stage` body=`{"to_stage":"contacted"}` → 200 + audit row.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Pipeline engine reused, not duplicated.

## Stop & report
Await "proceed" before Step 2.12.
