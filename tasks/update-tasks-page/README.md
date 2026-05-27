# Update Tasks page (upgrade)

A light follow-up to [tasks-page/](../tasks-page/), which shipped the v1 `/user/tasks` page with filter chips, sortable headers, quick-complete, and create/edit modal. This track adds the cross-CRM upgrade pattern: a richer assignee filter with "Me" preset, `last_activity_at` denormalisation (last comment / update), bulk actions (reassign / mark done / delete), and URL state.

## Why this exists

The Tasks page is already the most-feature-complete list in the app (per [tasks/tasks-page/](../tasks-page/)): filter chips, sortable headers, quick-complete checkbox, create / edit modal. Three small gaps remain to bring it in line with the other updated pages:

- **No assignee dropdown** — chips give "Mine" / "All" only; there's no "show me Anita's open tasks."
- **No `last_activity_at` column / sort** — `done_at` and `due_at` exist, but "when was the last update on this task" doesn't surface.
- **No bulk actions** — can't multi-select rows to bulk reassign or mark-done.
- **No URL state** — refresh / share / browser-back lose filter chip + sort state.

This is the smallest of the six update tracks — most of the heavy lifting was done in `tasks-page/`.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **`last_activity_at` column + sort** | Same denormalisation. Dispatch dict in `activities/service.py` extended to include `task`. |
| **Assignee dropdown filter** | Reuses `UsersDirectoryService`. Filters orthogonal to the existing chips (chip = scope; dropdown = which user inside that scope). |
| **Bulk actions** | Reuses `BulkActionBar`. Actions: Reassign / Mark done / Delete. |
| **URL state** | Reuses `UrlFilterStateDirective`. Round-trips chip + dropdown + sort + page. |

## What this does NOT do

- Does not add a board view, recurring tasks, subtasks, or templates — explicit follow-ups per [tasks-page/README.md](../tasks-page/README.md).
- Does not add tel / WhatsApp links (tasks have no phone field).
- Does not add CSV export (low value for tasks; defer if requested).
- Does not change quick-complete / create modal / sort behaviour — those are already correct.

## Acceptance criteria

A user on `/user/tasks`:

1. Sees a new **Last activity** column with relative time.
2. Can **sort by Last activity** by clicking the header.
3. Sees an **Assignee dropdown** in the filter row alongside the chips.
4. **Selecting an assignee** narrows the chip-scoped list to that user.
5. **Selecting rows** → BulkActionBar appears → Reassign / Mark done / Delete.
6. **URL reflects filters** — refresh / share / browser-back preserve chip + assignee + sort + page.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | Backend: `last_activity_at` + sort param + bulk endpoints + activity-hook dispatch | Pending | ~½ day |
| 2 | Frontend: Last activity column + assignee dropdown + BulkActionBar + URL state | Pending | ~½ day |

**Total: ~1 working day.** Stop and report after each per Rule 9.

## Dependencies

- [tasks-page/](../tasks-page/) — REQUIRED. Provides the v1 page this track upgrades.
- [update-contacts-page/](../update-contacts-page/) — REQUIRED. Provides `BulkActionBar`, `ReassignModal`, `UsersDirectoryService`, `UrlFilterStateDirective`, `RelativeTimePipe`.
- Tasks already has `assigned_to_id`; no model change for ownership.
- Tasks already has `tasks.write`; reassign reuses it (no new permission key).

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 1 new migration (`0056_tasks_last_activity.py`), 3 modified (`tasks/models.py`, `service.py`, `router.py`), 1 modified (`activities/service.py` dispatch). | Bulk endpoints: `POST /tasks/bulk-reassign`, `POST /tasks/bulk-mark-done`, `POST /tasks/bulk-delete`. |
| Step 2 frontend | 3 modified (`tasks-api.service.ts`, `tasks.page.ts/html`). | |
| Tests | `tests/core/tasks/test_last_activity_and_bulk.py`. | |

**Total ~7 files across 2 steps.**

## Self-check vs the 10 rules

- ✅ Rule 6 — no new permission key; existing `tasks.write` covers reassign.
- ✅ Rule 8 — 7 files; well under the limit.
- ✅ Rule 10 — bulk endpoints ship complete with the same audit pattern as contacts.

## After this track

- Tasks page caught up to the cross-CRM pattern.
- All five list pages (Contacts, Leads, Walk-ins, Appointments, Tasks) have the same shape: Owner / Last activity / sortable / filter dropdowns / bulk actions / URL state / shared primitives.
