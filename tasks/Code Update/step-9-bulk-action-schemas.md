# Step 9 — Shared bulk-action schemas

**Goal:** Consolidate identical `BulkReassign / BulkDelete / BulkAddTag` schemas in contacts, leads, tasks into one shared module.
**Track:** Code Update — Audit & Validation
**Depends on:** Step 4 (`ORMModel`)
**Status:** Not started

## Scope
**In-scope:**
- Create `api/src/app/shared/schemas/bulk_actions.py` exposing `BulkReassign`, `BulkDelete`, `BulkAddTag`, plus a generic `BulkActionResult(success_ids, failed: list[BulkFailure])`.
- Migrate contacts, leads, tasks schemas.

**Out of scope:**
- Bulk-action service base class (services keep their own per-entity logic).
- Bulk-import (separate manager-specced track in `tasks/bulk-import/`).

## Files to touch
- `api/src/app/shared/schemas/bulk_actions.py` (create)
- `api/src/app/core/contacts/schemas.py` (`:118-147`)
- `api/src/app/core/leads/schemas.py` (`:167-184`)
- `api/src/app/core/tasks/schemas.py`
- Router imports updated accordingly.

## Plan
1. Implement the three schemas + `BulkActionResult`.
2. Grep for `class Bulk\w+` in `core/*/schemas.py` → 3+ hits.
3. Replace with imports from `app/shared/schemas/bulk_actions`.
4. Confirm router request/response models unchanged.

## DB changes / migrations
None.

## Tests to add
- Unit: each schema validates a valid payload.
- Unit: empty `ids` list → 422.

## Verification checklist
- `uv run pytest` — green.
- Browser smoke: bulk-reassign 3 leads → succeeds.

## Self-check (10 rules)
- [ ] No leftover per-entity duplicates.

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
