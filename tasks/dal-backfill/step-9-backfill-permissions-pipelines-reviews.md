# Step 9 — Backfill DAL (permissions, pipelines, reviews)

**Goal:** Create `data_access.py` in three core modules. Move all SQL/ORM out of `service.py`. Behaviour unchanged.
**Status:** Pending
**Depends on:** Step 8.

---

## Scope

In-scope:
- `core/permissions/data_access.py` — **NEW**
- `core/pipelines/data_access.py` — **NEW**
- `core/reviews/data_access.py` — **NEW**
- Corresponding `service.py` updates.

Out of scope: behaviour changes.

## Files to touch

~6-8 files. ~350 lines net delta.

Per-module nuance:
- **permissions** — role+permission lookups; the `module_registry` permission composition. Hot path on every authenticated request. Move the role-permission join query as a single named DAL function and keep it cache-friendly.
- **pipelines** — pipeline + stage CRUD; used by leads kanban. The stage reorder write needs to stay transactional in service.
- **reviews** — review request + response queries; used by the Reviews feature (automation that sends review requests after a sale).

## Plan

Same pattern as Step 4.

## DB changes / migrations

None.

## Tests

Run existing pytests.

## Smoke

- **permissions:** Settings → Roles → load a role → permissions list correctly.
- **pipelines:** Leads kanban → add a stage → reorder stages → reload → persisted.
- **reviews:** Reviews page loads; trigger a review request → outbound row appears.

## Self-check (10 rules)

Pure relocation. ✓ Stop-and-report. ✓
