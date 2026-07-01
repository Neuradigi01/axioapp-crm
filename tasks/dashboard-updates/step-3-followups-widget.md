# Step 3 — Frontend: Today's Follow-ups widget

**Goal:** Ship the widget on `/user/dashboard` that renders Step 2's
endpoint — list of today's follow-ups with inline actions.
**Status:** COMPLETED
**Depends on:** Step 2 (endpoint live).

---

## Scope

### Placement

Below the KPI cards grid, before the recent-activity feed. Sits
side-by-side with the existing Upcoming Appointments widget on wide
screens, stacked on narrow.

### Component tree

- `todays-followups.component.ts` — the widget itself. Signal-based,
  standalone, OnPush.
- `todays-followups-api.service.ts` — thin HTTP wrapper around
  `GET /dashboard/followups`, plus `POST /tasks/{id}/complete` and
  `PATCH /tasks/{id}` for the inline actions.
- `reschedule-inline.component.ts` — inline datetime picker that
  swaps in when the user clicks Reschedule. Not a modal — inline
  matches the tightness of the row layout.

### Row shape

Each row renders as a Tailwind card:

```
┌────────────────────────────────────────────────────────────┐
│ [10:30]  Rahul Sharma · Sofa selection             [High]  │
│ ✉  Email                                                    │
│ "Send v2 quote with fabric swatches…"                       │
│                                                             │
│ [✓ Complete] [🕐 Reschedule] [→ Open lead]        [Pending]│
└────────────────────────────────────────────────────────────┘

Overdue rows get one extra action:

┌────────────────────────────────────────────────────────────┐
│ [Yesterday 14:00]  Priya Patel · Tourist visa      [Med]  │
│ 📞  Call                                                    │
│                                                             │
│ [✓ Complete] [🕐 Reschedule] [✗ Mark missed] [→ Open]      │
│                                                    [Overdue]│
└────────────────────────────────────────────────────────────┘
```

- Left edge — due time (HH:mm in org tz; "No time" if `due_at` is
  null).
- Header row — contact/lead label + priority chip (red/orange/blue).
- Type badge with a Lucide icon (phone / message-circle / mail /
  file-text / calendar-check / dot).
- Notes preview — first 80 chars of `task.notes`, `text-zinc-500`.
- Actions row — Complete + Reschedule + Open contact/lead deep-link.
- Right edge — status badge (Pending yellow / Completed green /
  Overdue red).

### Filters + search bar

Header of the widget:

- Left: **Today's Follow-ups (N)** counter.
- Middle: a compact chip strip with 5 buckets — **Today / Pending /
  Completed today / Overdue / Missed (7d)**. Clicking a chip
  re-fetches with the matching `bucket` param.
- Right: a search input (`q`) with 200ms debounce.

Advanced filters (assignee / type / priority) live behind a **⚙**
button that expands an inline row of pills.

### 60-second refresh

`setInterval(60_000)` inside `ngOnInit`, cleaned up via
`takeUntilDestroyed`. On refresh a subtle spinner appears on the
counter chip so the user knows the widget is live.

### Empty state

```
      📅
No follow-ups scheduled for today.
   [+ Add a task]
```

Add-a-task button navigates to the existing tasks-new modal at
`/user/tasks?new=1`.

### Inline action semantics

- **Complete** — `POST /tasks/{id}/complete` (already exists in tasks
  router). Widget optimistically flips the row to green Completed
  chip; on failure reverts + toasts.
- **Reschedule** — expands `reschedule-inline`, on save
  `PATCH /tasks/{id}` with new `due_at`. If new time isn't today, the
  row leaves the widget on the next refresh (or immediately if
  bucket=today).
- **Mark as missed** — only rendered when `status IN (open,
  in_progress)` AND `due_at < now` (overdue rows). Calls Step 6's
  `POST /tasks/{id}/mark-missed`. Widget optimistically flips the row
  to a red Missed chip; row leaves the Overdue bucket on next
  refresh.
- **Open** — Angular router link. Falls back to `/user/tasks/{id}`
  when there's no linked entity.

### Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/dashboard/widgets/todays-followups.component.ts` | **NEW** |
| `APP/src/app/features/user/core/dashboard/widgets/todays-followups.component.html` | **NEW** |
| `APP/src/app/features/user/core/dashboard/widgets/todays-followups-api.service.ts` | **NEW** |
| `APP/src/app/features/user/core/dashboard/widgets/reschedule-inline.component.ts` | **NEW** |
| `APP/src/app/features/user/core/dashboard/dashboard.page.html` | EDIT — mount widget below KPI grid |
| `APP/src/app/features/user/core/dashboard/dashboard.page.ts` | EDIT — import + register widget |

**~6 files, ~450 lines.**

---

## Verify

- Widget renders on `/user/dashboard` below the KPI grid.
- With no follow-ups today → empty state with illustration + "Add a
  task" CTA.
- Create a task due today via the Tasks page → within 60 seconds the
  widget's next auto-refresh picks it up.
- Click **Complete** → row flips green, "Pending today" chip counter
  decreases by 1.
- Click **Reschedule** → inline picker; pick tomorrow → row leaves
  the widget on next refresh.
- Click contact chip → navigates to the linked contact/lead detail
  page.
- Debounced search (200ms) filters live without page reload.
- 60-second poll visible via a small spinner tick every minute.

---

## Self-check

Rule 4 — form fields (reschedule datetime picker) render off the
existing tasks module's field registry, not hardcoded. Rule 8 —
right at the split threshold; if it grows past that, break
`reschedule-inline` into its own step. Rule 10 — no TODOs.

Prettier passes on every touched file.

Stop-report + wait for "proceed" before Step 4.
