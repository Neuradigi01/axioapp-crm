# Step 4 — Backfill DAL (activities, appointments, audit)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM queries out of `service.py` into `data_access.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Steps 1–3.

---

## Scope

In-scope:
- `core/activities/data_access.py` — **NEW**
- `core/appointments/data_access.py` — **NEW**
- `core/audit/data_access.py` — **NEW**
- Corresponding `service.py` updates in each (move queries out, keep transactions in).

Out of scope:
- Behaviour changes, new endpoints, new features.
- Refactoring helper service files (e.g. supplementary services stay where they are; only their query content moves to DAL).

## Files to touch

| Module | Files |
|---|---|
| activities | `data_access.py` (new) · `service.py` (modified) · any helper service files that touch DB (queries → DAL, transactions stay) |
| appointments | same |
| audit | same — note `audit/service.py` is currently open in IDE; common DB write paths from elsewhere call audit functions, so audit DAL is heavily used |

**~6-8 files. ~350 lines net delta.**

## Plan

For each module:
1. Open `service.py`. Identify every place that does `db.query / select / insert / update / delete / db.add / db.execute`. List them.
2. Create `data_access.py` with one function per identified DB op. Naming: `get_<entity>_by_id`, `list_<entity>`, `insert_<entity>`, `update_<entity>`, `delete_<entity>`. Pure data ops; no commits.
3. Rewrite `service.py` to call those DAL functions. `db.commit / refresh / flush` stays in service.
4. Run module-level smoke: one read + one write endpoint each.

Per-module nuance:
- **activities** — high call frequency from every other module that writes audit-trail-like rows. Keep insert function signatures compatible with current callers.
- **appointments** — has rescheduling logic; the date-range query (slot finding) is a single complex query, fine to move as-is.
- **audit** — every module writes audit events through audit service. Make sure the DAL function preserves the exact field set and ordering. Audit is read-heavy on the admin Audit Log page; that listing query (with filters + pagination) moves too.

## DB changes / migrations

None.

## Tests

- Run existing pytests for these three modules.

## Smoke

- **activities:** create a contact → activity row recorded.
- **appointments:** create an appointment → it appears on the calendar; reschedule → updates.
- **audit:** any write action → audit log shows the event in Settings → Audit Log.

## Self-check (10 rules)

Pure relocation. All 10 rules unchanged. ✓ < 10 files / < 400 lines. ✓ No new TODOs. ✓ Stop-and-report. ✓
