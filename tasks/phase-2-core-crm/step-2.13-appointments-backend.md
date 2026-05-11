# Step 2.13 — Appointments: backend

**Goal:** `appointments` table, conflict detection, CRUD, calendar listing endpoint (range-based).
**Phase:** 2
**Depends on:** 2.4, 1.5
**Status:** Pending

## Scope
**In-scope:**
- Model `Appointment` (TenantScoped): id, org_id, contact_id (FK), title, purpose (text — configurable, e.g., showroom_visit, measurement, delivery), scheduled_at, duration_min, location, status (scheduled/completed/cancelled/no_show), assigned_to_id (FK→users), custom_data JSONB, created_at, updated_at.
- Migration + RLS + indexes (`org_id, scheduled_at`, `assigned_to_id, scheduled_at`).
- Conflict detection: same `assigned_to_id` overlapping within `[scheduled_at, scheduled_at + duration_min)`.
- Endpoints: CRUD, `GET /appointments?from=&to=&assigned_to=` for calendar; `POST /appointments` returns 409 on conflict (with the conflicting appointment ids).
- Permission: `appointments.read`, `appointments.write`.

**Out of scope:**
- Frontend — 2.14.
- Field-visit appointments (Phase 4 reuses this engine).

## Files to touch
- `api/src/app/core/appointments/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0012_appointments.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Model + migration. Use `tstzrange` generated column or compute end_at as `scheduled_at + INTERVAL`.
2. Conflict check via `EXCLUDE USING gist` constraint OR a service-layer query before insert. Recommendation: service-layer query (simpler) + still add an `idx_assigned_at_scheduled_at` for fast lookup.
3. CRUD with conflict detection.
4. Calendar listing: returns flat array sorted by `scheduled_at`.
5. Activity log on create/move (`type='note'` payload `appointment created`).

## Tests to add
- `tests/test_appointments_crud.py`
- `tests/test_appointments_conflict.py` — overlapping with same assignee returns 409.

## Verification checklist
**Backend:**
- create A 10:00–11:00 for user X → 201.
- create B 10:30–11:30 for user X → 409.
- create C 10:30–11:30 for user Y → 201.
- `GET /appointments?from=…&to=…` → array.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Engine generic — `purpose` is free text/config.

## Stop & report
Await "proceed" before Step 2.14.
