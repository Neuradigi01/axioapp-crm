# Step 15 — Shared `BulkAction[]` config + modal state

**Goal:** Stop redefining the same `bulkActions = [reassign, delete, add-tag]` array + `bulkModal / bulkSubmitting / bulkError` signals in every list page. Fold into `ListPageState<T>`.
**Track:** Code Update — Frontend Foundation
**Depends on:** Step 13 (`ListPageState<T>`)
**Status:** Not started

## Scope
**In-scope:**
- Extend `ListPageState<T>` to accept a `bulkActions: BulkAction[]` config (per-entity, passed at construction).
- Move the canonical `BulkAction` interface to `core/shared/types/bulk-action.ts`.
- Each list page now passes its own array (with permission keys per entity), nothing else.

**Out of scope:**
- New bulk-action types beyond what already exists (reassign, delete, add-tag).

## Files to touch
- `core/shared/types/bulk-action.ts` (create / move)
- `core/shared/services/list-page.service.ts` (extend)
- `core/contacts/contacts-list.page.ts` (`:160-165, 168-171`)
- `core/leads/leads.page.ts`
- `core/tasks/tasks.page.ts` (`:140-144, 146-149`)
- `core/walk-ins/walk-ins.page.ts`
- `core/appointments/appointments.page.ts`

## Plan
1. Define canonical `BulkAction { key, label, icon, danger?, permissionKey }`.
2. Update `ListPageState` constructor to accept `bulkActions`.
3. Each page passes its array via the service constructor / injector; deletes the local `computed` block.

## DB changes / migrations
None.

## Tests to add
- Spec: bulk-action gating by permission key works.

## Verification checklist
- Browser smoke: each list page shows correct bulk actions for current role.

## Self-check (10 rules)
- [ ] Each page now just passes a config — no duplicated signal triplet.

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
