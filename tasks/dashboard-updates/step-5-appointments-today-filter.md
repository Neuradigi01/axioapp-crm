# Step 5 — Frontend: Appointments widget "Today" filter chip

**Goal:** Make the existing Upcoming Appointments widget mirror the
new Follow-ups widget — a **Today / Next 5** chip toggle so both
widgets answer "what's on my calendar today?" and "what's on deck?"
consistently.
**Status:** Pending
**Depends on:** Step 3 (visual parity target — same chip style).

---

## Scope

### Widget-level filter chip

The existing Upcoming Appointments list at the top-right of the
dashboard gets a compact 2-chip toggle in its header:

- **Today** — filters to `scheduled_at::date = today` in the org's
  timezone
- **Next 5** — current behavior (next 5 upcoming appointments, any
  day)

Default: **Today**. Toggle is signal-backed so no route change / no
page reload.

### Backend

`GET /dashboard/summary` already returns `upcoming_appointments` as
"next 5". Adding a query param would leak dashboard concerns into a
generic endpoint. Two paths, pick one:

- **Path A (preferred):** Add `?upcoming_scope=today|next5` (default
  `today`) to `/dashboard/summary`. Server does the filter.
- **Path B:** Filter client-side from the existing next-5 list.
  Simpler but shows N ≤ 5 today-appointments even if there are 8 —
  wrong count.

**Locked: Path A.** Small, backwards-compatible (default flip is
what the user actually wants), no client-side truncation issue.

### Rename / re-scope

The widget's title flips from "Upcoming Appointments" to
"Appointments" (single word), with the chip toggle beneath. Feels
more parallel to "Today's Follow-ups" beside it.

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/dashboard/service.py` | EDIT — accept `upcoming_scope` query param, split query into two branches |
| `APP/src/app/features/user/core/dashboard/dashboard.page.ts` | EDIT — chip toggle signal, re-fetch on toggle |
| `APP/src/app/features/user/core/dashboard/dashboard.page.html` | EDIT — chip UI in the appointments widget header |

**~3 files, ~120 lines.**

---

## Verify

- Widget header shows the toggle: **[Today] [Next 5]** with the
  default state **Today** active.
- With `scope=Today` selected → only today's appointments (in org
  tz) render; empty state renders when there are none.
- Flipping to **Next 5** → renders the previous behavior — next 5
  upcoming appointments regardless of day.
- Curl `GET /dashboard/summary` (no query param) → returns today's
  upcoming appointments (new default).
- Curl `GET /dashboard/summary?upcoming_scope=next5` → returns the
  next 5 regardless of day (backwards-compatible if any other caller
  relied on old behavior).

---

## Self-check

Rule 8 — 3 files, ~120 lines. Rule 10 — no TODOs.

Prettier passes.

Stop-report + wait for "proceed" before Step 6.
