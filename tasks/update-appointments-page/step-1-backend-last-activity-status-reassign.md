# Step 1 — Backend: `last_activity_at` + sort/filter + status transitions guarded + `appointments.reassign`

**Goal:** add `last_activity_at` to `appointments`, add sort + assignee + status filter to the list endpoint, lock the appointment state machine, register `appointments.reassign`, extend the activities-service dispatch.

**Depends on:** `update-contacts-page/` Step 1 (activities-hook dispatch).

## Files changed

### New
- `API/alembic/versions/0055_appointments_last_activity.py`
- `API/src/app/core/appointments/status_workflow.py`

### Modified
- `API/src/app/core/appointments/models.py`
- `API/src/app/core/appointments/schemas.py`
- `API/src/app/core/appointments/service.py`
- `API/src/app/core/appointments/router.py`
- `API/src/app/core/appointments/module.py` — register `appointments.reassign`.
- `API/src/app/core/activities/service.py` — extend dispatch.
- `API/src/app/core/permissions/role_templates.py` — grant `appointments.reassign` to Owner + Admin.

### Tests
- `API/tests/core/appointments/test_status_transitions.py` (new)

## Migration `0055_appointments_last_activity.py`

- `ALTER TABLE appointments ADD COLUMN last_activity_at TIMESTAMPTZ NULL`
- `CREATE INDEX ix_appointments_org_last_activity_desc ON appointments (org_id, last_activity_at DESC NULLS LAST)`
- Backfill from `activities` where `entity_type='appointment'`.
- `downgrade()` reverses.

## `status_workflow.py`

```python
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"completed", "no_show", "cancelled"}),
    "completed": frozenset(),
    "no_show": frozenset({"scheduled"}),  # re-book after no-show
    "cancelled": frozenset({"scheduled"}),
}
```

## `models.py`

Add `last_activity_at: Mapped[datetime | None]`. Confirm `assigned_to_id` and `status` are already present (per Phase 2).

## `schemas.py`

- `AppointmentListItem`, `AppointmentOut`: + `last_activity_at`.
- `AppointmentUpdate`: status validator → `ALLOWED_TRANSITIONS`.

## `service.py`

- `list_appointments(...)` gains `sort: 'scheduled_at' | 'created_at' | 'last_activity_at'`, `order`, `assigned_to_id`, `status`, `scheduled_from`, `scheduled_to`.
- Default sort: `scheduled_at asc` (upcoming first).
- `update_appointment(...)` enforces state machine.

## `router.py`

`GET /appointments` adds: `sort`, `order`, `assigned_to_id`, `status`, `scheduled_from`, `scheduled_to`.

## `module.py`

Register `appointments.reassign`.

## `role_templates.py`

- Owner — auto-granted.
- Admin / Store Manager — granted.
- Sales Exec / Design Consultant / Warehouse — NOT granted by default (Admin can edit).

## `activities/service.py`

`_LAST_ACTIVITY_TABLES` += `{"appointment": Appointment}`.

## Test `test_status_transitions.py`

1. `scheduled → completed` succeeds.
2. `scheduled → scheduled` rejected (no-op disallowed).
3. `completed → scheduled` rejected (terminal).
4. `cancelled → scheduled` (rebook) succeeds.
5. Activity-insert bumps `last_activity_at`.
6. `list?sort=last_activity_at&order=desc` correct ordering.

## Acceptance

- `uv run alembic upgrade head` succeeds.
- State machine enforced.
- Existing appointments tests pass.

## Self-check vs the 10 rules

- ✅ Rule 6 — `appointments.reassign` registered.
- ✅ Rule 8 — 9 files; under limit.
- ✅ Rule 10 — state machine complete.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 9.
> **What you can verify:**
> 1. `uv run alembic upgrade head` adds the column.
> 2. Activity-insert bumps `last_activity_at`.
> 3. State machine enforced.
> 4. `appointments.reassign` registered.
> **Tests added:** `test_status_transitions.py` (6).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 2.
