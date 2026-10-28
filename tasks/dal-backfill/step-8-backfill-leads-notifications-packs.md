# Step 8 — Backfill DAL (leads, notifications, packs)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** COMPLETED
**Depends on:** Step 7. (Leads' router-violation was already fixed in Step 1; this step is the full DAL backfill for the same module.)
**Effort:** ~0.75 days (leads is query-heavy; packs is the module-registry discovery package, not the `packs/` directory).

---

## Scope

In-scope:
- `core/leads/data_access.py` — **NEW**
- `core/notifications/data_access.py` — **NEW**
- `core/packs/data_access.py` — **NEW** (the `core/packs/` module = pack discovery + install state, NOT the `api/src/app/packs/` directory)
- Corresponding `service.py` updates.

Out of scope: behaviour changes. The Step 1 routing-config fix already extracted that one commit; this step relocates the remaining leads queries.

## Files to touch

~6-9 files. ~400 lines net delta.

Per-module nuance:
- **leads** — biggest of the three. List endpoint with pipeline-stage + assignee + source filters, lead detail with embedded contact + activities + last touch. Dedup query (Step 1 of Lead Capture) lives here. Move every query as a named DAL function — including dedup, routing config read, source-attribution writes.
- **notifications** — per-user feed reads + mark-as-read writes. WebSocket delivery layer doesn't move (that's transport, not data).
- **packs** — pack registry queries (which packs installed per org, install state). Read-heavy. Used by the module registry on every request to decide which packs are active.

## Plan

Same pattern as Step 4. Leads may push budget — if > 400 lines, split leads into its own step.

## DB changes / migrations

None.

## Tests

Run existing pytests (leads has the most coverage in this batch).

## Smoke

- **leads:** kanban loads; create a lead via quick-add; reassign; move across stage.
- **notifications:** trigger a notification (e.g. assign a task to self) → bell badge updates → mark as read.
- **packs:** open Settings → Packs (if surfaced) or check `/api/v1/packs/installed` returns the expected list.

## Self-check (10 rules)

Pure relocation. ✓ Watch leads size. ✓ Stop-and-report. ✓
