# Step 3.4 — Staff module: backend

**Goal:** Reuse `users` + `roles`. Add `staff_profiles` (commission_rate, monthly_target, rating, employment_status). Endpoints for staff list, performance, attendance, activity logs.
**Phase:** 3
**Depends on:** 1.5
**Status:** COMPLETED

## Scope
**In-scope:**
- Model `StaffProfile` (TenantScoped): user_id PK (FK→users), commission_rate Numeric(5,2), monthly_target Numeric, rating Numeric(2,1), employment_status enum (active/leave/terminated), joined_at, updated_at.
- Model `Attendance` (TenantScoped): id, user_id, clock_in_at, clock_out_at, hours (generated), date (date), notes.
- Migration + RLS + indexes.
- Endpoints `/api/v1/staff`:
  - `GET /staff` — list users with their profile data.
  - `GET /staff/{id}/performance` — leads converted, sales, target progress, rating.
  - `GET /staff/{id}/attendance?from=&to=`
  - `GET /staff/{id}/activity` — joined activities table filtered by user_id.
  - `POST /staff/{id}/clock-in`, `/clock-out` (used both by admin override and staff portal).
- Permissions: `staff.read`, `staff.write`, `attendance.write`.

**Out of scope:**
- Frontend admin view — 3.5.
- Staff portal auth — 3.6.

## Files to touch
- `api/src/app/core/staff/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0016_staff_profiles_attendance.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Models + migration. `Attendance.hours` generated as `EXTRACT(EPOCH FROM (clock_out_at - clock_in_at))/3600`.
2. Performance endpoint composes from leads (won count), invoices (later — placeholder summing 0 in this step), target ratio.
3. Clock-in disallows two open sessions for the same user/day.
4. Module descriptor (sidebar: "Staff").

## Tests to add
- `tests/test_staff_profiles.py`
- `tests/test_attendance.py` — overlap rejection.

## Verification checklist
**Backend:**
- `GET /staff` → list with profile fields.
- `POST /staff/{id}/clock-in` → 201; second call → 409.
- `GET /staff/{id}/performance` → JSON with target/progress/rating.

## Self-check (10 rules)
- [ ] org_id + RLS.

## Stop & report
Await "proceed" before Step 3.5.
