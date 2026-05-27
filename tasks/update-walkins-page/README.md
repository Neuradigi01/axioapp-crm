# Update Walk-ins page

A focused track to bring `/user/walk-ins` up to standard-CRM expectations for the showroom flow: status workflow surfaced (Waiting / With Staff / Done / Walked-out), last-activity sort, single + bulk reassign of assigned staff, walk-in → lead conversion, and row ergonomics (tel / WhatsApp). Reuses the shared primitives from [update-contacts-page/](../update-contacts-page/).

## Why this exists

Walk-ins already has `assigned_to_id` and a `status` field on the model, but the UI surfaces neither well:

- **`status` not shown as a column nor as a filter** — managers can't see at a glance who's "Waiting" vs "With Staff."
- **No `last_activity_at`** — same denormalisation gap as everywhere else.
- **No workflow buttons** — moving a walk-in through statuses requires opening the edit modal.
- **No reassign UI** — Store Manager can't transfer a walk-in to a different staff member from the list.
- **No "Convert to Lead"** button — walk-in is captured but turning it into a lead means re-entering.
- **No tel / WhatsApp** on visitor phone — friction in the most phone-driven part of the funnel.
- **Filters are basic** — no Today / This-week chip; no assignee dropdown.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **`last_activity_at` column + sort** | Same denormalisation as contacts; activity hook dispatch extended. |
| **Status column + workflow buttons** | Status as a coloured pill; row-level "Mark with-staff," "Mark done," "Mark walked-out" buttons (state-machine validated). |
| **Status filter chips** | All · Waiting · With Staff · Done · Walked-out. |
| **Date chip filters** | Today · This week · This month. |
| **Owner column + assignee filter** | Reuses `UsersDirectoryService` + scope toggle. |
| **Single + bulk reassign** | `ReassignModal` + `BulkActionBar`. New permission key `walk_ins.reassign`. |
| **Walk-in → Lead conversion** | "Convert to Lead" button — creates a lead pre-filled with the visitor's info, links it back to the walk-in. |
| **Row ergonomics** | tel / WhatsApp on visitor phone, URL state, styled confirm delete. |

## What this does NOT do

- Does not change the existing walk-in **register** flow (registration tablet / kiosk path).
- Does not add a queue-display board view (separate v2 polish — needs a poll-based push or websocket).
- Does not add SLA timers / overdue badges (depends on org settings; defer).
- Does not add bulk delete (walk-ins are historical records; deletion is rare and 1-at-a-time is fine).
- Does not add CSV export (not requested; can be added in a v2 polish step).

## Acceptance criteria

A Store Manager on `/user/walk-ins`:

1. Sees **Status column** with coloured pills.
2. Sees **Owner column** with the assigned staff.
3. Sees **Last activity** column with relative time.
4. Can filter by **Status chips** + **Today / This-week / This-month chips** + **Assignee dropdown**.
5. Can click row-level **status buttons** to advance the walk-in (Mark with-staff → Mark done) without opening the modal.
6. Can select rows and **bulk reassign** to a different staff member.
7. Can click a single walk-in's pencil-Owner icon to reassign.
8. Can click **"Convert to Lead"** → modal pre-fills visitor name/phone/email → confirm → lead created, walk-in linked.
9. Phone cell is **click-to-call**; WhatsApp icon next to it.
10. **URL reflects filters** — refresh-safe.
11. **Junior staff** sees no reassign / no convert buttons (gated).

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: `last_activity_at` + sort/filter + status transitions guarded + `walk_ins.reassign` | Pending | ~½ day |
| 2 | Frontend: Status / Owner / Last activity columns + status chips + scope toggle | Pending | ~½ day |
| 3 | Walk-in → Lead conversion + row ergonomics + bulk reassign | Pending | ~½ day |

**Total: ~1.5 working days.** Stop and report after each per Rule 9.

## Dependencies

- [update-contacts-page/](../update-contacts-page/) — REQUIRED. Provides all shared primitives.
- [update-leads-page/](../update-leads-page/) — recommended (the convert flow lands a lead; ideally the lead detail / list already shows the new fields).
- Activities service hook — dispatch dict extended to include `walk_in`.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 new migration (`0054_walkins_last_activity.py`), 4 modified (`walk_ins/models.py`, `schemas.py`, `service.py`, `router.py`), 1 modified (`activities/service.py` dispatch). | |
| Step 2 frontend | 3 modified (`walk-ins-api.service.ts`, `walk-ins.page.ts/html`). | |
| Step 3 frontend | 1 new (`walkin-convert-modal.component.ts/html`), 1 modified (`walk-ins-api.service.convert(...)`), 2 modified (`walk-ins.page.ts/html` for bulk select + tel/wa + URL state). | |
| Tests | `tests/core/walk_ins/test_status_transitions.py`, `test_convert.py`. | |

**Total ~12 files across 3 steps.**

## Self-check vs the 10 rules

- ✅ Rule 1, 5, 7 — `core/walk_ins/` untouched at boundaries.
- ✅ Rule 6 — `walk_ins.reassign` registered via module registry.
- ✅ Rule 8 — ≤10 files per step.
- ✅ Rule 10 — convert is atomic; status transitions enforced.

## After this track

- Walk-ins becomes a real showroom worklist.
- Convert-to-Lead closes the showroom-to-funnel gap that currently requires manual re-entry.
