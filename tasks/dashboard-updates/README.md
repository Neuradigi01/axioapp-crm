# Dashboard updates — Follow-ups + KPI polish

**Manager spec 2026-07-01.** Every user opens the dashboard first thing
in the morning to answer one question: **"what do I need to do today?"**
Right now that answer is incomplete — Appointments are surfaced as a
list, but Follow-ups (tasks to call / message / email a customer) only
appear as a bare count. This track fills that gap.

---

## The conceptual split we're locking in

| Concept | Table | Who does it | Time |
|---|---|---|---|
| **Follow-up** — action to take (Call · WhatsApp · Email · Document reminder · Other) | `tbl_tasks` | Employee alone | `due_at` (soft, "by when") |
| **Appointment** — meeting to attend (Office meeting · Video call · Product demo · Site visit) | `tbl_appointments` | Employee + customer | `scheduled_at` (fixed slot) |

Both matter, both belong on the dashboard, both need parallel
treatment. Today only appointments get the list widget — this track
adds the follow-ups widget + polishes the appointments widget so they
mirror.

---

## Scope for v1 (this track)

**In scope:**

- New `followup_type` enum column on `tbl_tasks` — Call · WhatsApp ·
  Email · Document · Meeting · Other (Meeting kept because a rep may
  log "meeting reminder" as a task without booking an actual
  appointment).
- New `missed` value added to the existing `TaskStatus` enum — used
  as a terminal state when the rep gives up on a follow-up (customer
  didn't respond, cancelled, no longer relevant).
- New **Mark as missed** inline action on the widget's overdue rows +
  a nightly Celery grooming job that auto-flips tasks overdue by more
  than 7 days from `open` → `missed` so the Overdue bucket doesn't
  grow unbounded.
- New `GET /api/v1/dashboard/followups` endpoint — list + summary
  counts (today / pending / completed / overdue / missed), server-side
  filters + pagination, RBAC scope (Owner/Admin see org; Employee sees
  own).
- Frontend "Today's Follow-ups" list widget on the dashboard, with
  inline **Complete · Reschedule · Mark as missed · Open contact**
  actions.
- Three new KPI cards next to "Open tasks": **Pending today ·
  Completed today · Overdue** (both org + personal scope variants).
  Click a card → filters the widget.
- "Today" filter chip on the existing Upcoming Appointments widget so
  it can flip between today-only and next-5.
- 60-second refresh interval on the widget (poll, not websocket — the
  websocket track is separate).

**Out of scope (deferred):**

- Support tickets — `core/support/` module doesn't exist yet;
  ticket-linked follow-ups drop out of v1. Add when tickets ship.
- Department + Manager-team scope — RBAC today is Owner / Admin /
  Employee. No team hierarchy; "Manager sees their team" collapses to
  Admin (all-in-org). Revisit when teams ship.
- WebSocket push refresh — 60s polling is enough for v1. Real-time
  push belongs to the notifications-websocket track.
- "Add Notes" quick action — the Task detail already has notes on the
  entity's timeline; not worth re-inventing an inline notes modal
  here.
- Bulk actions on the follow-ups list — one-row-at-a-time only in v1.

---

## Track structure

| Step | Title | Status | Files |
|---|---|---|---|
| 1 | [Schema — `followup_type` + `missed` status on tbl_tasks](step-1-followup-type-schema.md) | **COMPLETED** | 4 |
| 2 | [Backend — `/dashboard/followups` endpoint](step-2-followups-api.md) | Pending | 5 |
| 3 | [Frontend — Today's Follow-ups widget](step-3-followups-widget.md) | Pending | 6 |
| 4 | [Frontend — 3 new KPI cards + card→widget filter wiring](step-4-followup-kpi-cards.md) | Pending | 3 |
| 5 | [Frontend — Appointments widget "Today" filter chip](step-5-appointments-today-filter.md) | Pending | 3 |
| 6 | [Missed status: mark-as-missed action + nightly grooming](step-6-mark-as-missed-and-grooming.md) | Pending | 5 |
| 7 | [Tests + smoke](step-7-tests-and-smoke.md) | Pending | 3 |

**Total: 7 steps, ~28 files, ~2-2.5 days of work.**

---

## Locked design decisions

- **Follow-ups = Tasks, one table.** No new `tbl_followups` — that
  would duplicate `tbl_tasks` (same due date, same assignee, same
  status). The distinction is a `followup_type` column, not a separate
  table. Simpler for reporting + no cross-table union queries on the
  dashboard.
- **Overdue is derived; Missed is stored.** *Overdue* = `due_at <
  now AND status IN (open, in_progress)` — a filter over live tasks
  the rep can still act on. *Missed* is a distinct terminal status
  the rep sets explicitly (or the grooming job sets after 7 days) —
  closes the loop, keeps history, keeps the Overdue count bounded.
  Two different concepts, deliberately named differently.
- **Server-side scope, not client-side.** Employee-vs-Admin visibility
  is enforced in the endpoint (same pattern the dashboard summary
  already uses — `users.read` permission → org scope, otherwise
  personal). Frontend never branches on role name.
- **Two hero cards for personal scope reshuffle.** Personal scope
  today shows: My tasks · My leads · My appointments · My conversion.
  We'll swap "My conversion" out of hero for "Pending today" — the
  daily-driver number matters more than a lagging conversion metric
  in the hero strip. Conversion stays in the secondary card row.
- **60-second poll, not WebSocket.** Aligns with how the existing
  dashboard summary already refreshes. WebSocket-driven live
  dashboard is a separate track.

---

## Risks

- **KPI card explosion.** Personal scope will grow from 4 hero + N
  secondary → 4 hero + N+3 secondary. The dashboard cards grid is
  already ~7 cards on Owner scope. Watch for visual crowding — if the
  grid feels heavy, gate 2 of the 3 new cards behind a "Show more"
  toggle rather than shipping all 3 flat.
- **Task without a linked contact.** A rep can create a standalone
  task ("review pipeline") that has no `contact_id`. The widget must
  render these cleanly ("no linked contact") instead of blanking the
  row.
- **Follow-up type migration on existing rows.** All existing tasks
  will backfill to `followup_type='other'` in the migration.
  Documented in Step 1's migration.
- **Timezone.** "Today" in the query is the org's timezone, not UTC.
  `tbl_appointments.scheduled_at` conversion already handles this
  pattern; we mirror it for `tbl_tasks.due_at`.

---

## What "done" looks like

A user in Ajay's Workspace can:

1. Open `/user/dashboard` → see **Today's Follow-ups (N)** widget
   below the KPI grid, showing tasks due today, sorted by due time
   ascending then priority descending.
2. See 4 KPI cards for follow-ups: **My open tasks · Pending today ·
   Completed today · Overdue** — each clickable to filter the widget.
3. Click **Complete** on a row → row flips to green "Completed" chip,
   the "Pending today" count goes down by 1, the "Completed today"
   count goes up by 1.
4. Click **Reschedule** on a row → inline datetime picker; save →
   row leaves the widget if new time isn't today.
5. Click **Mark as missed** on an overdue row → row flips to a red
   "Missed" chip and leaves the Overdue bucket.
6. Click the row's contact chip → navigates to the linked contact /
   lead detail page.
7. Toggle the Appointments widget between **Today** and **Next 5** —
   both render cleanly.
8. Empty state for follow-ups reads *"No follow-ups scheduled for
   today."* with a small illustration.
9. RBAC: Employee sees only rows where `assigned_to_id = self`; Owner
   / Admin see all rows in-org.
10. Nightly grooming job runs at 02:00 (org tz) — any task with
    `due_at < now - 7d` AND `status = open` flips to `missed`.
    Visible on the Tasks page under the Missed filter for audit.
