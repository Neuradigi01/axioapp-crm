# Step 2 — Frontend: Status / Owner / Last activity columns + status chips + scope toggle + date chips

**Goal:** surface status as a column (coloured pill) and a chip filter; add Owner + Last activity columns; add Today/This-week/This-month date chips; wire scope toggle.

**Depends on:** Step 1 backend + `update-contacts-page/` Step 2 (`RelativeTimePipe`, `UsersDirectoryService`).

## Files changed

### Modified
- `APP/src/app/features/user/core/walk-ins/walk-ins-api.service.ts`
- `APP/src/app/features/user/core/walk-ins/walk-ins.page.ts`
- `APP/src/app/features/user/core/walk-ins/walk-ins.page.html`

## `walk-ins-api.service.ts`

- Extend types with `last_activity_at`.
- Extend `WalkInListQuery` with `sort`, `order`, `assigned_to_id`, `status`, `date_from`, `date_to`.

## `walk-ins.page.ts`

Signals:
```typescript
readonly sortKey = signal<'time_in' | 'last_activity_at' | 'created_at'>('time_in');
readonly sortOrder = signal<'asc' | 'desc'>('desc');
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
readonly statusFilter = signal<string>('');  // '' | 'waiting' | 'with_staff' | 'done' | 'walked_out'
readonly dateChip = signal<'' | 'today' | 'week' | 'month'>('');
readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());
readonly users = toSignal(this.usersDir.list(), { initialValue: [] });
```

`dateChip` translates to `date_from` / `date_to` server-side.

Status row-buttons handler:
```typescript
async advanceStatus(walkIn: WalkInListItem, target: string) {
  await this.api.update(walkIn.id, { status: target });
  this.reload();
}
```
Buttons hidden when transition is not allowed (mirror server state machine on FE).

## `walk-ins.page.html`

**Filter row:**
- Status chips: All · Waiting · With Staff · Done · Walked-out.
- Date chips: Today · This week · This month.
- Scope toggle (My / Team / All; hidden for junior).
- Assignee dropdown.

**Table columns:**
- (keep existing) Visitor / Phone / Time-in
- Add **Status** column (coloured pill: waiting=amber, with_staff=blue, done=emerald, walked_out=zinc).
- Add **Owner** column.
- Add **Last activity** column.
- Action column: render row-level status-transition buttons:
  - From `waiting`: "Mark with-staff" | "Walked out"
  - From `with_staff`: "Mark done" | "Walked out"
  - From `walked_out`: "Re-engage"
  - From `done`: (none)
  Use small text buttons or icon-only with tooltip to keep the row compact.

## Acceptance

1. Status column with coloured pills.
2. Status chips filter the list.
3. Row-level status buttons fire the transition (or are hidden when not allowed).
4. Today / This-week / This-month chips filter by date.
5. Scope toggle works; junior sees no toggle.
6. Owner + Last activity columns populated.
7. URL state **not** yet wired (Step 3).

## Lucide icons used

`user-check`, `coffee`, `door-closed`, `check-circle-2` (status buttons). Verify all registered.

## Self-check vs the 10 rules

- ✅ Rule 4 — static columns; no dynamic-form path.
- ✅ Rule 5 — sidebar untouched.
- ✅ Rule 8 — 3 files; well under limit.

## Stop-and-report template

> ✅ Step 2 complete.
> **Files changed:** 3.
> **What you can verify:**
> 1. Status column + chips + row-level transition buttons.
> 2. Owner + Last activity columns.
> 3. Date chips filter by today/week/month.
> 4. Scope toggle works; junior sees only Mine.
> **Tests added:** none (FE smoke).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 3 (convert + bulk + ergonomics).
