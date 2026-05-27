# Step 1 — Backend: `last_activity_at` + sort param + bulk endpoints + activity-hook dispatch

**Goal:** add `last_activity_at` to `tasks` (bumped on activity insert + on task update/comment), expose it as a sort key on the existing list endpoints, add three bulk endpoints (reassign / mark-done / delete).

**Depends on:** `update-contacts-page/` Step 1 (activities-hook dispatch pattern), [tasks-page/](../tasks-page/) v1 endpoints.

## Files changed

### New
- `API/alembic/versions/0056_tasks_last_activity.py`

### Modified
- `API/src/app/core/tasks/models.py`
- `API/src/app/core/tasks/schemas.py`
- `API/src/app/core/tasks/service.py`
- `API/src/app/core/tasks/router.py`
- `API/src/app/core/activities/service.py` — extend dispatch.

### Tests
- `API/tests/core/tasks/test_last_activity_and_bulk.py` (new)

## Migration `0056_tasks_last_activity.py`

- `ALTER TABLE tasks ADD COLUMN last_activity_at TIMESTAMPTZ NULL`
- `CREATE INDEX ix_tasks_org_last_activity_desc ON tasks (org_id, last_activity_at DESC NULLS LAST)`
- Backfill: `UPDATE tasks SET last_activity_at = GREATEST(updated_at, COALESCE(done_at, '-infinity'::timestamptz), COALESCE((SELECT MAX(created_at) FROM activities WHERE entity_type='task' AND entity_id=tasks.id), '-infinity'::timestamptz))`.
  - For tasks, `last_activity_at` is the most-recent of: `updated_at`, `done_at`, or any logged activity. The simplest semantic the user expects.
- `downgrade()` drops index + column.

## `models.py`

Add `last_activity_at: Mapped[datetime | None]`.

## `schemas.py`

- `TaskOut`, `TaskListItem`: + `last_activity_at`.
- Bulk request schemas:
  - `TaskBulkReassign { ids: list[UUID], assigned_to_id: UUID | None }`
  - `TaskBulkMarkDone { ids: list[UUID] }`
  - `TaskBulkDelete { ids: list[UUID] }`

## `service.py`

- `list_all_tasks(...)`, `list_my_tasks(...)`: gain `sort: 'due_at' | 'priority' | 'created_at' | 'last_activity_at' | 'title'`, `order: 'asc' | 'desc'`. Whitelist server-side.
- New service functions:
  - `bulk_reassign_tasks(ids, assigned_to_id)` — loops + writes audit activity per row.
  - `bulk_mark_done_tasks(ids)` — sets status=done, done_at=now per id (skips already-done).
  - `bulk_delete_tasks(ids)` — hard delete (matches single delete semantic).
- Also bump `last_activity_at` from inside `update_task` and `mark_task_done` — independent of activity-insert hook, because not every task update creates an activity.

## `router.py`

- Add `sort`, `order` query params to `GET /tasks/all` and `GET /tasks/me`.
- Mount four endpoints:
  - `POST /tasks/bulk-reassign` — requires `tasks.write`.
  - `POST /tasks/bulk-mark-done` — `tasks.write`.
  - `POST /tasks/bulk-delete` — `tasks.write`.
  - (Single `POST /tasks/{id}/reassign` already covered by `PATCH /tasks/{id}` body field — no new endpoint.)

## `activities/service.py`

`_LAST_ACTIVITY_TABLES` += `{"task": Task}`.

## Test `test_last_activity_and_bulk.py`

1. Activity-insert on a task bumps `last_activity_at`.
2. `update_task` (e.g., title change) bumps `last_activity_at` (independent of activity).
3. `bulk_reassign` updates N rows + writes N audit activities.
4. `bulk_mark_done` sets all to done; rows already done unchanged.
5. `bulk_delete` removes all rows.
6. `list_all_tasks?sort=last_activity_at&order=desc` returns expected order.

## Acceptance

- `uv run alembic upgrade head` succeeds.
- Existing tasks tests still pass.

## Self-check vs the 10 rules

- ✅ Rule 6 — no new permission key; reuses `tasks.write`.
- ✅ Rule 8 — 6 files; well under limit.
- ✅ Rule 10 — bulk endpoints ship complete.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 6.
> **What you can verify:**
> 1. `uv run alembic upgrade head` adds column.
> 2. Activity-insert + task update both bump `last_activity_at`.
> 3. Bulk endpoints work.
> 4. Sort by `last_activity_at` honoured on both list endpoints.
> **Tests added:** `test_last_activity_and_bulk.py` (6).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 2.
