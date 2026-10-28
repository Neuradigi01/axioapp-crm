# Step 2 — Frontend list: Owner, Status, Last activity columns + sortable + status filter + scope toggle

**Goal:** surface the new backend fields in the leads list view. Add status chips, scope toggle (My / Team / All), assignee dropdown, and sortable headers. Pipeline view changes land in Step 3.

**Depends on:** Step 1 backend + `update-contacts-page/` Step 2 (`RelativeTimePipe`, `UsersDirectoryService`).

## Files changed

### Modified
- `APP/src/app/features/user/core/leads/leads-api.service.ts`
- `APP/src/app/features/user/core/leads/leads.page.ts`
- `APP/src/app/features/user/core/leads/leads.page.html`

## `leads-api.service.ts`

- Extend `LeadListItem` / `Lead` / `LeadCreate` / `LeadUpdate` with `last_activity_at`, `lost_reason`, `lost_reason_other`.
- Extend `LeadListQuery` with `sort`, `order`, `last_activity_lt`, `last_activity_gt`. Pass new params through `list(...)`.

## `leads.page.ts`

Signals:
```typescript
readonly sortKey = signal<'created_at' | 'last_activity_at' | 'contact_name'>('created_at');
readonly sortOrder = signal<'asc' | 'desc'>('desc');
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
readonly statusControl = new FormControl<string>('', { nonNullable: true });
readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());
readonly users = toSignal(this.usersDir.list(), { initialValue: [] });
readonly noActivityFilter = signal<'' | '7d' | '14d' | '30d'>('');
```

`defaultScopeForRole()`:
- Junior Sales / Sales Exec → `'mine'`, scope toggle hidden.
- Senior Sales / Design Consultant → `'team'`.
- Store Manager / Admin / Owner → `'all'`.

`toggleSort(key)` flips order or sets new key. `noActivityFilter` translates to `last_activity_lt = now - {7,14,30}d`.

## `leads.page.html`

**Filter row** — augment the existing 4-column grid:
- **Status chips** (above the grid or inline): All · New · Contacted · Qualified · Won · Lost.
- **Scope toggle** (segmented button): My · Team · All (hidden for junior).
- **Assignee dropdown** alongside the existing source filter.
- **"No activity" chip** dropdown: Any · 7d · 14d · 30d (drives the `noActivityFilter` signal).

**List view table** — add to header:
- Make Created and Last activity columns sortable (chevron icon on active).
- Add **Owner** column (avatar + name + Unassigned fallback).
- Add **Status** column (coloured pill: new=zinc, contacted=blue, qualified=violet, won=emerald, lost=red).
- Add **Last activity** column (`{{ item.last_activity_at | relativeTime }}`).

**Pipeline view** — leave the card structure unchanged; the per-card upgrade lands in Step 3.

## Status pill component (inline, no new file)

A small inline pill helper in `leads.page.html`:
```html
<span class="rounded-full px-2 py-0.5 text-[10px] font-medium"
      [class]="statusClass(item.status)">
  {{ statusLabel(item.status) }}
</span>
```
`statusClass()` returns a Tailwind class string per status. `statusLabel()` returns "New" / "Contacted" / etc.

## Acceptance

1. List view shows Status, Owner, Last activity columns.
2. Sorting works on Created / Last activity / Contact name.
3. Status chips filter the list (`?status=qualified`).
4. Scope toggle switches between My / Team / All. Junior sales rep doesn't see the toggle (default forced to Mine).
5. Assignee dropdown shows "All / Me / Unassigned / <users>"; picking "Me" resolves to caller's user id.
6. "No activity > 7d" chip filters out leads with recent activity.
7. Pipeline view unchanged in this step (Step 3 adds card upgrades).
8. URL state is **not** wired in this step — Step 4 adds it.

## Lucide icons used

`chevron-up`, `chevron-down` already registered from `update-contacts-page/`. Verify `circle-dot` (or chosen status icon) is registered.

## Self-check vs the 10 rules

- ✅ Rule 4 — first-class fields render in static cells.
- ✅ Rule 5 — sidebar untouched.
- ✅ Rule 8 — 3 files; well under limit.

## Stop-and-report template

> ✅ Step 2 complete.
> **Files changed:** 3 (leads-api.service.ts, leads.page.ts/html).
> **What you can verify:**
> 1. List view: Owner, Status, Last activity columns visible.
> 2. Sortable Created / Last activity / Contact name headers.
> 3. Status chips + Scope toggle + Assignee dropdown + "No activity" chip working.
> 4. Junior sales rep sees no scope toggle; defaults to Mine.
> **Tests added:** none (FE smoke in browser).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 3 (pipeline cards + bulk select).
