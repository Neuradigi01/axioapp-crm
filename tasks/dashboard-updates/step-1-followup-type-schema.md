# Step 1 — Schema: `followup_type` + `missed` status on tbl_tasks

**Goal:** Two additive schema changes so the dashboard widget can
(a) render Call · WhatsApp · Email · Document · Meeting · Other type
badges and (b) show + count the terminal `missed` status. Both
changes live on `tbl_tasks` so they land in one migration.
**Status:** Pending
**Depends on:** Nothing (foundation step).

---

## Scope

### Extend `tbl_tasks`

Add one nullable column:

- `followup_type` TEXT with a Postgres ENUM check constraint —
  allowed values: `call`, `whatsapp`, `email`, `document`, `meeting`,
  `other`.

Nullable is deliberate: existing rows and Celery-created tasks (e.g.
"follow up on this lead" auto-tasks) don't have to specify a type.
The widget renders `NULL` as **Other**.

### Enum + index for `followup_type`

- New Postgres enum `task_followup_type` with the 6 values above.
- Partial index `ix_tbl_tasks_org_due_type_pending` on
  `(org_id, due_at, followup_type) WHERE status IN ('open',
  'in_progress')` — the dashboard hits this exact shape (org-scoped,
  ordered by due_at, filtered by type + open status).

### Extend `task_status` enum — add `missed`

The existing `task_status` Postgres enum today has `open`,
`in_progress`, `done`. Add a 4th terminal value:

- `missed` — rep gave up on the follow-up (customer non-responsive,
  cancelled, no longer relevant). Set explicitly via the widget's
  Mark-as-missed action (Step 6) OR by the nightly grooming job (also
  Step 6) when a task is overdue by more than 7 days.

Migration uses `ALTER TYPE task_status ADD VALUE 'missed'` — safe,
non-blocking, no data rewrite. Existing rows at `open` / `in_progress`
/ `done` are untouched.

The Python `TaskStatus` enum on the ORM gets the matching member.

### RLS

No change — `tbl_tasks` already has the standard `org_id =
current_setting('app.current_org_id')` policy from its original
creation.

### Backfill

The migration leaves existing rows at their current `followup_type =
NULL` and their current `status` values — no data-shape rewrite. The
widget treats a NULL `followup_type` as **Other** so display stays
consistent.

### Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/0148_task_followup_type_and_missed_status.py` | **NEW** — enum + column + index + `ALTER TYPE task_status ADD VALUE 'missed'` |
| `API/src/app/core/tasks/models.py` | EDIT — add `followup_type` column + `TaskFollowupType` enum class + `missed` member to `TaskStatus` |
| `API/src/app/core/tasks/schemas.py` | EDIT — add `followup_type` to `TaskCreate` / `TaskUpdate` / `TaskRead`, add `missed` to any status literals |

**~3 files, ~150 lines.**

---

## Verify

- `docker exec crm-api-1 alembic upgrade head` runs clean; enum +
  column + index exist:
  ```sql
  SELECT column_name, data_type FROM information_schema.columns
  WHERE table_name = 'tbl_tasks' AND column_name = 'followup_type';
  -- → followup_type | USER-DEFINED (task_followup_type)

  SELECT unnest(enum_range(NULL::task_status));
  -- → open, in_progress, done, missed

  SELECT indexname FROM pg_indexes
  WHERE tablename = 'tbl_tasks' AND indexname LIKE '%followup%';
  -- → ix_tbl_tasks_org_due_type_pending
  ```
- `alembic downgrade -1` also runs clean — note Postgres can't drop
  a single enum value, so downgrade recreates `task_status` without
  `missed` (throwing if any rows currently use it, which is expected
  before Step 6 lands).
- Existing task create flow still works — POSTing a task without
  `followup_type` succeeds and stores `NULL`. POSTing a task with
  `status='open'` / `'in_progress'` / `'done'` / `'missed'` all
  succeed.

---

## Self-check

Rule 2 — new column is on the tenant-scoped table; RLS still active.
Rule 8 — 3 files, ~120 lines, well under the split threshold. Rule
10 — no TODOs, no commented-out code, no placeholder values.

Stop-report + wait for "proceed" before Step 2.
