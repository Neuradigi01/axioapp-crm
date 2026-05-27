# Step 2 — Frontend: Last activity column + assignee dropdown + BulkActionBar + URL state

**Goal:** finish the cross-CRM pattern on the tasks page. Surface the new column, add the assignee dropdown (orthogonal to existing chips), wire bulk actions, and round-trip filter state through the URL.

**Depends on:** Step 1 + `update-contacts-page/` Steps 2–4 (`RelativeTimePipe`, `UsersDirectoryService`, `BulkActionBar`, `ReassignModal`, `ConfirmDialog`, `UrlFilterStateDirective`).

## Files changed

### Modified
- `APP/src/app/features/user/core/tasks/tasks-api.service.ts`
- `APP/src/app/features/user/core/tasks/tasks.page.ts`
- `APP/src/app/features/user/core/tasks/tasks.page.html`

## `tasks-api.service.ts`

- Extend `Task` / `TaskListItem` with `last_activity_at`.
- Extend list query with `sort`, `order`.
- Add bulk methods: `bulkReassign(ids, userId)`, `bulkMarkDone(ids)`, `bulkDelete(ids)`.

## `tasks.page.ts`

Signals to add:
```typescript
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
readonly users = toSignal(this.usersDir.list(), { initialValue: [] });
readonly selectedIds = signal<Set<string>>(new Set());
readonly bulkActions = computed<BulkAction[]>(() => [
  { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'tasks.write' },
  { key: 'done', label: 'Mark done', icon: 'check-circle-2', permissionKey: 'tasks.write' },
  { key: 'delete', label: 'Delete', icon: 'trash-2', danger: true, permissionKey: 'tasks.write' },
]);
```

URL state config: chip + sortKey + sortOrder + assignee + page.

`onBulkAction(key)` opens the corresponding modal (ReassignModal for reassign; ConfirmDialog for done + delete).

## `tasks.page.html`

- Insert a new column **Last activity** (between Due / Priority and Assignee — choose the position that doesn't push horizontal scroll).
- Make Last activity column header sortable.
- Add Assignee dropdown in the filter row (next to existing chips). Selecting "All" doesn't restrict; selecting a user filters.
- Prepend a checkbox column (row + header).
- Mount `<app-bulk-action-bar>` + the three modals.
- Apply `[appUrlFilterState]` directive to the host.

Existing quick-complete checkbox stays in place (independent of the new selection checkbox; they live in different columns).

## Acceptance

1. Last activity column visible + sortable.
2. Assignee dropdown filters orthogonally to chip scope.
3. Selecting rows shows BulkActionBar.
4. Bulk reassign / mark-done / delete work; permission-gated.
5. URL state round-trips chip + assignee + sort + page.
6. Junior sales rep: bulk actions visible if they have `tasks.write` (no extra reassign-permission gate on tasks — that was the design choice in `update-tasks-page/README.md`).

## Lucide icons used

`user-cog`, `check-circle-2`, `trash-2`. All registered.

## Self-check vs the 10 rules

- ✅ Rule 8 — 3 files; well under limit.

## Stop-and-report template

> ✅ Step 2 complete. Tasks track done.
> **Files changed:** 3.
> **What you can verify:**
> 1. Last activity column + sortable.
> 2. Assignee dropdown filter.
> 3. Bulk reassign / mark-done / delete.
> 4. URL state preserves all filter + sort + page.
> **Tests added:** none (FE smoke; backend bulk tested in Step 1).
> **Self-check:** all 10 rules ✅.
> **Tasks track complete.** Recommend proceeding to `update-staff-offboarding/`.
