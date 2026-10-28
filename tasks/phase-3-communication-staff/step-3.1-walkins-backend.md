# Step 3.1 — Walk-ins: backend

**Goal:** `walk_ins` table with universal status flow (browsing/interested/follow_up/converted/left). Quick-register endpoint optimized for reception desk.
**Phase:** 3
**Depends on:** 2.4
**Status:** COMPLETED

## Scope
**In-scope:**
- Model `WalkIn` (TenantScoped): id, org_id, contact_id (FK→contacts), time_in, time_out, duration_min (generated column), requirement, budget, assigned_to_id, status enum, custom_data JSONB, notes, created_at, updated_at.
- Migration + RLS + indexes.
- Endpoints: `/api/v1/walk-ins` CRUD, `POST /walk-ins/quick-register` (single call: creates contact if not exists by phone, then creates walk-in), `PATCH /walk-ins/{id}/checkout` sets `time_out`.
- Permission keys: `walkins.read`, `walkins.write`.
- Module descriptor (sidebar entry).

**Out of scope:**
- Frontend — 3.2.

## Files to touch
- `api/src/app/core/walk_ins/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0014_walk_ins.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Model + migration; `duration_min` as `GENERATED ALWAYS AS (EXTRACT(EPOCH FROM (time_out - time_in))/60) STORED` (NULL when time_out is null).
2. CRUD endpoints; quick-register service: lookup contact by `(org_id, phone)`, create if missing, then walk-in.
3. Custom-data validated against `walk_in` field defs.

## Tests to add
- `tests/test_walkins_crud.py`
- `tests/test_walkins_quick_register.py` — phone match reuses existing contact.

## Verification checklist
**Backend:**
- `POST /walk-ins/quick-register` body=`{phone:"9999",full_name:"X",requirement:"sofa"}` → 201, returns walk-in + contact.
- `PATCH /walk-ins/{id}/checkout` → `time_out` set, `duration_min` computed.

## Self-check (10 rules)
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 3.2.
