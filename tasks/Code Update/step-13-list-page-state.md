# Step 13 — `ListPageState<T>` service

**Goal:** Extract the pagination / sort / filter / selection / bulk-modal signal cluster duplicated across 5+ list pages into one reusable state service.
**Track:** Code Update — Frontend Foundation
**Depends on:** Step 12 (`BaseApiService<T>`)
**Status:** Not started

## Scope
**In-scope:**
- Create `app/src/app/features/user/core/shared/services/list-page.service.ts` — generic `ListPageState<T, Q>` exposing signals:
  - `items / loading / loadError / total`
  - `page / pageSize / totalPages` (computed)
  - `selectedIds / selectedCount / allOnPageSelected`
  - `bulkModal / bulkSubmitting / bulkError`
  - methods: `load() / setPage() / setPageSize() / toggleSelection() / selectAllOnPage() / clearSelection() / openBulkModal() / closeBulkModal()`
- Migrate `contacts-list.page.ts`, `leads.page.ts`, `tasks.page.ts`, `walk-ins.page.ts`, `appointments.page.ts`.

**Out of scope:**
- Custom-column visibility (`update-leads-page` track owns that).
- Pipeline-view-specific state on leads.

## Files to touch
- `core/shared/services/list-page.service.ts` (create)
- `core/shared/services/list-page.service.spec.ts` (create)
- `core/contacts/contacts-list.page.ts` (`:71-80, 94-96, 139-143, 147-170`)
- `core/leads/leads.page.ts` (`:151-180+`)
- `core/tasks/tasks.page.ts` (`:94-99, 108-116, 137-139`)
- `core/walk-ins/walk-ins.page.ts`
- `core/appointments/appointments.page.ts`

## Plan
1. Implement `ListPageState<T, Q>` constructor taking `(api: BaseApiService<T>, defaults: { pageSize: number })`.
2. Signal mutation methods auto-trigger `load()` when relevant (page/pageSize change → re-fetch).
3. For each list page: inject `ListPageState<Entity>`, remove duplicated signals, wire template bindings.
4. Browser smoke each page.

## DB changes / migrations
None.

## Tests to add
- Unit: state transitions (page change triggers reload; selection toggles).
- Spec: bulk-modal flow.

## Verification checklist
- `ng test` — green.
- `ng build` — clean.
- Browser smoke: paginate / filter / bulk-select on each migrated page.

## Self-check (10 rules)
- [ ] No duplicated pagination state left in any list page.
- [ ] No `setTimeout` polling sneaked in.

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
