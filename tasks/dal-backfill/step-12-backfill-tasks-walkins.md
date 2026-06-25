# Step 12 — Backfill DAL (tasks, walk_ins)

**Goal:** Create `data_access.py` in two core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 11.

---

## Scope

In-scope:
- `core/tasks/data_access.py` — **NEW**
- `core/walk_ins/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes. This step closes out the core-module backfill bucket.

## Files to touch

~4-6 files. ~250 lines net delta.

Per-module nuance:
- **tasks** — task CRUD + assignee + due-date queries. The org-wide tasks list (from `tasks-page` track) has a composite query — move it as one DAL function.
- **walk_ins** — walk-in records + assignee. Used by Walk-Ins page; lightweight.

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **tasks:** `/user/tasks` list loads; create a task; reassign; mark done.
- **walk_ins:** Walk-Ins page loads; log a walk-in; reassign.

## Self-check (10 rules)

Pure relocation. ✓ Stop-and-report. ✓
