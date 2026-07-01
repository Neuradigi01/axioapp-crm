# Step 6 — Mark-as-missed action + nightly grooming job

**Goal:** Give reps a way to explicitly close the loop on a follow-up
they've given up on ("customer's not responding"), and auto-close
stale-open ones so the Overdue count doesn't grow unbounded.
**Status:** Pending
**Depends on:** Step 1 (`missed` in the `TaskStatus` enum) + Step 3
(widget renders the button) + Step 2 (endpoint's `missed` bucket).

---

## Scope

### Backend — `POST /api/v1/tasks/{task_id}/mark-missed`

Endpoint that flips a task from `open` / `in_progress` → `missed`.
Refuses when the task is already terminal (`done` or `missed`) with
409, so a stale click can't overwrite completion history.

Layered:

- **`router.py`** — thin: parse, call service, return.
- **`service.py`** — permission check (assignee or `tasks.manage`),
  status-transition guard (`open` / `in_progress` → `missed` only),
  writes an audit-log entry (`tasks.marked_missed`) so the timeline
  on the linked contact shows why the follow-up stopped.
- **`data_access.py`** — `mark_task_missed(session, task_id, actor_id)`
  — pure UPDATE + returns the mutated row.

### Backend — Celery grooming task

`groom_stale_open_tasks` in `core/tasks/tasks.py`. Cross-tenant sweep
(same pattern as `google_calendar.reconcile_pending` — opens a session
without tenant context, uses raw SQL to bypass the RLS filter):

```sql
UPDATE tbl_tasks
SET status = 'missed',
    updated_at = now()
WHERE status IN ('open', 'in_progress')
  AND due_at < (now() - INTERVAL '7 days')
RETURNING id, org_id
```

Returned rows get an audit entry (`tasks.auto_missed`) so the change
is traceable. Beat schedule: `crontab(hour=2, minute=0)` — 02:00 UTC.
Simple daily tick, no per-org-timezone gymnastics — a 7-day threshold
means the timezone slack (max ±14 hours) doesn't matter.

### Frontend — button already added in Step 3

Step 3 already wired the **Mark as missed** button visually; this
step's frontend work is the API service method + optimistic update
logic:

- `TodaysFollowupsApiService.markMissed(taskId)` — POSTs to the new
  endpoint, returns the updated Task.
- Widget optimistic path — row's status flips to `'missed'` locally
  and re-classifies (leaves the Overdue bucket, joins the Missed
  bucket on next refresh). On failure the local flip reverts + a
  toast surfaces the error.

### Beat + worker wiring

- Add `'src.app.core.tasks.tasks'` to the Celery autodiscover list
  in `API/src/celery/worker.py` (if not already there).
- Add the beat entry to `API/src/celery/celery_config.py`:
  ```python
  "groom-stale-open-tasks": {
      "task": "src.app.core.tasks.tasks.groom_stale_open_tasks",
      "schedule": crontab(hour=2, minute=0),
  }
  ```

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/tasks/router.py` | EDIT — add `POST /{task_id}/mark-missed` route |
| `API/src/app/core/tasks/service.py` | EDIT — `mark_task_missed_service` with permission + transition guard + audit log |
| `API/src/app/core/tasks/data_access.py` | EDIT — `mark_task_missed` DAL helper |
| `API/src/app/core/tasks/tasks.py` | **NEW** — `groom_stale_open_tasks` Celery task (or extend existing file if one exists) |
| `API/src/celery/celery_config.py` | EDIT — beat schedule entry |
| `APP/src/app/features/user/core/dashboard/widgets/todays-followups-api.service.ts` | EDIT — `markMissed()` method |

**~5-6 files, ~250 lines.**

---

## Verify

- `curl -X POST /api/v1/tasks/{id}/mark-missed` as the assignee →
  200 · task row's `status = 'missed'` in DB · audit entry with action
  `tasks.marked_missed` created.
- Same call as a different (non-assignee, no `tasks.manage`) user →
  403.
- Same call on an already-`done` task → 409.
- Trigger the beat task manually:
  ```powershell
  docker exec crm-celery-1 celery -A src.celery.worker.celery call `
      src.app.core.tasks.tasks.groom_stale_open_tasks
  ```
  In a test org, seed one task with `due_at = now() - INTERVAL '8
  days'` AND `status = 'open'` → after the task runs, row's status
  = `'missed'` + audit entry `tasks.auto_missed` created.
- Widget: click **Mark as missed** on an overdue row → row flips to
  red Missed chip instantly (optimistic) → Overdue count in the KPI
  card drops by 1 → on next 60s refresh row leaves the Overdue bucket.

---

## Self-check

Rule 6 — permission key reused (`tasks.manage`); no new key. Rule 8 —
5-6 files, ~250 lines, well under the split threshold. Rule 10 — no
TODOs.

Prettier passes on the frontend file.

Stop-report + wait for "proceed" before Step 7.
