# Step 7 — Tests + smoke

**Goal:** Pin the follow-ups endpoint, widget behavior, mark-as-missed
action, and nightly grooming with pytest + run the end-to-end smoke
against Ajay's Workspace.
**Status:** Pending
**Depends on:** Steps 1-6 shipped.

---

## Scope

### Pytest cases (~14)

`API/tests/dashboard/test_followups.py`:

- Owner scope: endpoint returns `scope=org`, sees every task in-org.
- Employee scope: endpoint returns `scope=personal`, filters to
  `assigned_to=self`, ignores `assigned_to` query param
  (URL-hacking guard).
- `bucket=today` sort — earlier `due_at` first, then priority
  desc (high before medium before low).
- `bucket=pending` — status `open`/`in_progress` only, no `done`
  or `missed`.
- `bucket=completed_today` — status `done` AND `completed_at::date =
  today`. Yesterday's completed tasks don't show.
- `bucket=overdue` — `due_at < now` AND `status IN
  (open, in_progress)`. Today's future-due tasks don't show;
  already-completed tasks don't show; **`missed` tasks are excluded**.
- `bucket=missed` — status `missed` AND `updated_at::date >= today -
  7d`. Older missed tasks are excluded from the widget (still visible
  on the Tasks page's Missed filter).
- Counts object — `missed_last_7d` is populated + matches
  `bucket=missed` result count.
- Search `q=` matches contact full_name, phone, email, or task
  title (case-insensitive).
- `followup_type` filter — `email` only returns email-typed tasks;
  legacy NULL rows treated as `other`.
- Pagination — page 1 · page_size 5 returns 5 items, total > 5.

`API/tests/tasks/test_mark_missed.py`:

- Happy path — assignee POSTs mark-missed on an `open` task → 200 ·
  row's status = `'missed'` · audit entry `tasks.marked_missed`
  created.
- Permission — non-assignee without `tasks.manage` → 403.
- Transition guard — POSTing on a `done` task → 409.
- Transition guard — POSTing twice on the same task → second call
  409 (already `missed`).

`API/tests/tasks/test_groom_stale.py`:

- Task with `due_at = now - 8d AND status = 'open'` → task
  auto-flips to `missed` after `groom_stale_open_tasks` runs.
- Task with `due_at = now - 5d AND status = 'open'` → NOT flipped
  (inside the 7-day grace window).
- Task with `due_at = now - 10d AND status = 'done'` → NOT flipped
  (already terminal).
- Cross-tenant sweep — tasks from 2 different orgs, both eligible,
  both get flipped in one run.

### Jest / Angular tests

Deferred — the Angular test harness for dashboard widgets isn't set
up (same convention as Steps 5/6 of google-calendar-sync). Behavior
is covered by the runbook smoke.

### Smoke runbook

`tasks/dashboard-updates/smoke-runbook.md`:

Target: `ajaygogane224@gmail.com` in Ajay's Workspace (org
`41f9ede9-41b3-44ce-b489-3004566d4068`).

1. Create 6 tasks via the Tasks page — 2 due today (call + email
   type), 1 due yesterday (overdue), 1 due 10 days ago (should get
   auto-groomed to missed), 1 due tomorrow, 1 already completed
   today.
2. Reload `/user/dashboard`.
3. Widget shows the 2 today-pending tasks, sorted correctly.
4. KPI cards: **Pending today = 2 · Completed today = 1 · Overdue
   = 2** (the yesterday + the 10-days-ago ones, since grooming hasn't
   run yet).
5. Click **Overdue** card → widget scrolls into view, list flips to
   the 2 overdue tasks.
6. Click **Complete** on the today-pending call task → row flips
   green, Pending today drops to 1, Completed today rises to 2.
7. Click **Reschedule** on the remaining today-pending email task →
   inline picker → pick tomorrow → save → row leaves the widget on
   next refresh.
8. Click **Mark as missed** on the yesterday-overdue row → row flips
   red Missed chip instantly · Overdue count drops to 1 · Missed
   (7d) count rises to 1.
9. Trigger the grooming task manually:
   ```powershell
   docker exec crm-celery-1 celery -A src.celery.worker.celery call `
       src.app.core.tasks.tasks.groom_stale_open_tasks
   ```
   → the 10-days-ago task auto-flips to `missed` · Overdue count
   drops to 0 · Missed (7d) count still 1 (older-than-7d exits the
   widget's Missed bucket).
10. Wait 60 seconds → widget auto-refreshes; counter updates without
    a page reload.
11. Empty state — reschedule the last one to tomorrow → widget shows
    the empty-state illustration + "Add a task" CTA.
12. Log in as a non-Owner employee → open dashboard → widget shows
    only that employee's own tasks (visual RBAC confirmation).

### Files to touch

| File | Action |
|---|---|
| `API/tests/dashboard/test_followups.py` | **NEW** |
| `API/tests/tasks/test_mark_missed.py` | **NEW** |
| `API/tests/tasks/test_groom_stale.py` | **NEW** |
| `tasks/dashboard-updates/smoke-runbook.md` | **NEW** |
| `tasks/dashboard-updates/README.md` | EDIT — mark step statuses COMPLETED |

**~5 files, ~600 lines.**

---

## Verify

- `docker exec crm-api-1 python -m pytest tests/dashboard/test_followups.py tests/tasks/test_mark_missed.py tests/tasks/test_groom_stale.py -v`
  passes all ~22 cases.
- Runbook smoke on Ajay's Workspace completes 1-12 without visual
  glitches, count drift, or console errors.

---

## Self-check

Test isolation — each test opens a fresh session with a scoped org
+ user fixture; no cross-test bleed. Rule 8 — 3 files, ~450 lines,
right at threshold.

Stop-report.
