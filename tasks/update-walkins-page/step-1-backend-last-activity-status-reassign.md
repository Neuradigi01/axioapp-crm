# Step 1 — Backend: `last_activity_at` + sort/filter + status transitions guarded + `walk_ins.reassign`

**Goal:** add `last_activity_at` to `walk_ins`, surface sort + filter on the list endpoint, lock walk-in status transitions in a state machine, register the `walk_ins.reassign` permission key, and extend the activities-service dispatch.

**Depends on:** `update-contacts-page/` Step 1 (activities-hook dispatch pattern), `update-leads-page/` Step 1 (state-machine pattern reused).

## Files changed

### New
- `API/alembic/versions/0054_walkins_last_activity.py`
- `API/src/app/core/walk_ins/status_workflow.py`

### Modified
- `API/src/app/core/walk_ins/models.py`
- `API/src/app/core/walk_ins/schemas.py`
- `API/src/app/core/walk_ins/service.py`
- `API/src/app/core/walk_ins/router.py`
- `API/src/app/core/walk_ins/module.py` — register `walk_ins.reassign`.
- `API/src/app/core/activities/service.py` — extend dispatch to include `walk_in`.
- `API/src/app/core/permissions/role_templates.py` — grant `walk_ins.reassign` to Owner + Admin templates.

### Tests
- `API/tests/core/walk_ins/test_status_transitions.py` (new)

## Migration `0054_walkins_last_activity.py`

- `ALTER TABLE walk_ins ADD COLUMN last_activity_at TIMESTAMPTZ NULL`
- `CREATE INDEX ix_walkins_org_last_activity_desc ON walk_ins (org_id, last_activity_at DESC NULLS LAST)`
- Backfill from `activities` where `entity_type='walk_in'` (same SQL pattern as `0052`).
- `downgrade()` reverses.

## `status_workflow.py`

```python
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "waiting": frozenset({"with_staff", "walked_out"}),
    "with_staff": frozenset({"done", "walked_out"}),
    "done": frozenset(),
    "walked_out": frozenset({"waiting"}),  # re-engage on return
}
```

## `models.py`

Add `last_activity_at: Mapped[datetime | None]`. No other model changes — `assigned_to_id` and `status` already present.

## `schemas.py`

- `WalkInListItem`, `WalkInOut`: + `last_activity_at`.
- `WalkInUpdate`: status validator references `ALLOWED_TRANSITIONS`.

## `service.py`

- `list_walk_ins(...)` gains `sort: 'time_in' | 'last_activity_at' | 'created_at'`, `order`, `assigned_to_id`, `status`, `date_from`, `date_to`.
- Default sort: `time_in desc`.
- `update_walk_in(...)` enforces state-machine.

## `router.py`

`GET /walk-ins` adds: `sort`, `order`, `assigned_to_id`, `status`, `date_from`, `date_to`.

## `module.py`

Register `walk_ins.reassign`.

## `role_templates.py`

- Owner — auto-granted.
- Admin / Store Manager — granted.
- Sales Exec / Junior — NOT granted.

## `activities/service.py`

`_LAST_ACTIVITY_TABLES` += `{"walk_in": WalkIn}`.

## Test `test_status_transitions.py`

1. `waiting → with_staff` succeeds.
2. `waiting → done` rejected (must go through with_staff).
3. `done → waiting` rejected (terminal).
4. `walked_out → waiting` succeeds (re-engagement).
5. Activity-insert on walk-in bumps `last_activity_at`.
6. `list?sort=last_activity_at&order=desc` returns expected order.

## Acceptance

- `uv run alembic upgrade head` succeeds; index visible.
- All existing walk-ins tests still pass.
- Status transitions enforced.

## Self-check vs the 10 rules

- ✅ Rule 6 — `walk_ins.reassign` via module.
- ✅ Rule 8 — 9 files; under limit.
- ✅ Rule 10 — state machine complete.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 9 (1 migration, 1 new state-machine, 5 modified walk_ins, 1 modified activities, 1 modified role-templates, 1 new test).
> **What you can verify:**
> 1. `uv run alembic upgrade head` adds the column + index.
> 2. Activity-insert bumps `last_activity_at`.
> 3. State machine enforced (curl PATCH with bad transition → 422).
> 4. `walk_ins.reassign` registered.
> **Tests added:** `test_status_transitions.py` (6).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 2.
