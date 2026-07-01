# Smoke runbook — Today's Follow-ups widget

**Purpose.** End-to-end smoke of the follow-ups widget + KPI cards +
Appointments Today/Next 5 toggle + Mark-as-missed + nightly grooming
against Ajay's Workspace. Run once after each release lands in
staging or production; the runbook doubles as the ops team's
"is-it-broken?" checklist.

**Target org.** `41f9ede9-41b3-44ce-b489-3004566d4068` (Ajay's
Workspace), Owner `ajaygogane224@gmail.com`. Chosen because it's the
canonical smoke target across every dashboard-updates step (per the
project memory).

**Prerequisites.**

1. Migration `0148_task_type_and_missed` applied at DB head.
2. API up (`docker ps` shows `crm-api-1` healthy).
3. Celery worker + beat up (`crm-celery-1` + `crm-celery-beat-1`),
   with `src.app.core.tasks.tasks.groom_stale_open_tasks` in the
   registered task list.
4. Angular dev server (`http://localhost:4207`) or the deployed FE
   pointing at the API.

---

## 12-step walkthrough

Time budget: ~10 minutes end-to-end.

### 1. Seed 6 test tasks via the Tasks page (2 min)

Log in as `ajaygogane224@gmail.com`. Nav to **Tasks → New task**.
Create the following (assignee = self for all):

| # | Title | Due | Status seeded | Follow-up type |
|---|---|---|---|---|
| 1 | Discovery call · smoke | Today 10:00 | open (default) | Call |
| 2 | Send v2 quote PDF · smoke | Today 14:00 | open | Email |
| 3 | Yesterday's follow-up · smoke | Yesterday 15:00 | open | Call |
| 4 | Stale customer chase · smoke | 10 days ago | open | Call |
| 5 | Tomorrow's demo · smoke | Tomorrow 10:00 | open | Meeting |
| 6 | Old completed thing · smoke | Today | done (mark done post-create) | Email |

*(Row 6: create as open first, then click Complete on the tasks list
page. Row 4: use the calendar picker to backdate `due_at` — the New
Task modal supports past dates.)*

### 2. Reload `/user/dashboard` (5s)

Refresh the browser. The Today's Follow-ups widget appears below the
KPI grid, side-by-side with Appointments on wide screens.

### 3. Widget shows today-open tasks correctly (10s)

- Bucket chip **Today** is active (highlighted black).
- Row count in header = **3** (rows 1, 2, 6 — all due today, mix of
  open + done).
- Sort order: `Discovery call · smoke` (10:00) → `Send v2 quote PDF ·
  smoke` (14:00) → `Old completed thing · smoke` (done row, at end).

### 4. KPI cards reflect the seed (10s)

Scroll to the secondary card grid (or Owner hero if you have
`users.read`). Verify:

- **Follow-ups pending today** = 2 (rows 1 + 2)
- **Follow-ups completed today** = 1 (row 6)
- **Follow-ups overdue** = 2 (rows 3 + 4)

*(Owner scope shows these in the secondary grid. Employee scope has
Pending today in the hero + the other two in secondary.)*

### 5. Click the Overdue card (5s)

- Page smoothly scrolls to the widget.
- Widget's bucket chip flips from **Today** to **Overdue**.
- List body now shows 2 rows: `Yesterday's follow-up · smoke` +
  `Stale customer chase · smoke`, oldest first.

### 6. Complete a pending task (10s)

Click **Today** chip → click **[✓ Complete]** on
`Discovery call · smoke`.

- Row flips green **Completed** chip instantly (optimistic).
- Within a beat (silent refresh) the Pending today card drops to 1;
  Completed today rises to 2.

### 7. Reschedule the other today-pending row (15s)

Click **[🕐 Reschedule]** on `Send v2 quote PDF · smoke`.

- The action bar collapses into an inline datetime picker.
- Set the picker to tomorrow at 10:00 → click **Save**.
- Row leaves the Today bucket on the next refresh; Pending today
  card drops to 0.

### 8. Mark the yesterday-overdue row as missed (15s)

Flip to the **Overdue** chip. The row for
`Yesterday's follow-up · smoke` now shows a red **[✗ Mark missed]**
button between Reschedule and Open.

- Click **[✗ Mark missed]**.
- Row flips to red **Missed** chip instantly.
- Overdue card counter drops to 1.
- Flip to the **Missed (7d)** chip → the row appears there.

### 9. Trigger the grooming task manually (30s)

```powershell
docker exec crm-celery-1 celery -A src.celery.worker.celery call `
    src.app.core.tasks.tasks.groom_stale_open_tasks
```

Watch Flower (`http://localhost:5555`) or Celery logs for the task
completion:

```
Task src.app.core.tasks.tasks.groom_stale_open_tasks[...] succeeded
in ~3s: {'swept': 1, 'at': '...'}
```

Refresh the widget:

- `Stale customer chase · smoke` (row 4) has been flipped to
  `missed` by the grooming query.
- The Overdue card counter drops to 0.
- The row is NOT visible in the Missed (7d) widget bucket (its
  `updated_at` is now within the last 7 days, but the seeded
  `due_at` was 10 days ago — the bucket filters by
  `updated_at::date >= today - 7d`, so it DOES appear here — verify
  the row is now visible in the Missed bucket).

### 10. 60s auto-refresh (60s wait)

Leave the widget open for a full minute. A small spinner appears
next to the widget title mid-poll; counters and rows update without
a full page reload.

### 11. Empty state (30s)

Delete or reschedule the remaining rows so no follow-up is due
today. The widget's Today body swaps to the empty state:

```
        📅
No follow-ups scheduled for today.
       [+ Add a task]
```

Click **Add a task** → navigates to `/user/tasks?new=1` (new-task
modal opens).

### 12. RBAC — non-Owner employee (2 min)

Log in as a non-Owner employee in the same org (any Employee-role
account). Open `/user/dashboard`. The Follow-ups widget:

- Shows **only** tasks whose `assigned_to_id = self`. None of the
  Owner-seeded rows above appear.
- Personal-scope hero includes Pending today (replacing My
  conversion). Owner-scope hero is unchanged.
- URL-hacking check: append `?assigned_to=<owner-uuid>` to the API
  call in a curl / fetch — the endpoint ignores the param and still
  returns only the employee's own rows.

### Appointments toggle spot-check (30s)

While the dashboard is open:

- The Appointments widget's title reads **Appointments** (not
  "Upcoming appointments").
- Two chips below the title: **Today** (active) + **Next 5**.
- With no appointments scheduled for today, the widget shows the
  empty state *"No appointments scheduled for today."*
- Click **Next 5** → widget re-fetches; up to 5 future appointments
  render regardless of day.

---

## Cleanup

Delete the 6 `· smoke`-suffixed rows via the Tasks page's bulk-delete
so the next smoke run has a clean slate:

```sql
DELETE FROM tbl_tasks
 WHERE org_id = '41f9ede9-41b3-44ce-b489-3004566d4068'
   AND title LIKE '%· smoke';
```

---

## What "green" looks like

Every step above completes as written, no console errors, no visual
glitches (row-height jitter, counter divergence between chip and
card, missing icons). If a step takes longer than **~10 seconds** to
reflect (excluding the intentional 60-second auto-refresh and the
async Celery task hop), inspect in this order:

1. **API logs** — `docker logs crm-api-1 --tail 50` — any 500s?
2. **Celery logs** — `docker logs crm-celery-1 --tail 100` — is the
   grooming task registered? Any tracebacks?
3. **DB row inspection** — connect via `psql` and check
   `tbl_tasks.status` matches what the widget claims.
4. **Browser network tab** — are the `/dashboard/summary` and
   `/dashboard/followups` calls returning 200 with the expected
   shape?
