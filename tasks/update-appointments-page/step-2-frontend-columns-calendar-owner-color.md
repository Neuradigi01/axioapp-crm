# Step 2 — Frontend list + calendar: Owner / Status / Last activity columns + calendar owner-color + scope toggle

**Goal:** surface the new fields in list view. In calendar view, color-code events by Owner. Add status chips, scope toggle, assignee dropdown.

**Depends on:** Step 1 backend + `update-contacts-page/` Step 2.

## Files changed

### New
- `APP/src/app/features/user/core/shared/owner-color.util.ts` — deterministic palette mapping user id → Tailwind colour class.

### Modified
- `APP/src/app/features/user/core/appointments/appointments-api.service.ts`
- `APP/src/app/features/user/core/appointments/appointments.page.ts`
- `APP/src/app/features/user/core/appointments/appointments.page.html`

## `owner-color.util.ts`

```typescript
const PALETTE = [
  { bg: 'bg-blue-100', text: 'text-blue-800', ring: 'ring-blue-200' },
  { bg: 'bg-emerald-100', text: 'text-emerald-800', ring: 'ring-emerald-200' },
  { bg: 'bg-amber-100', text: 'text-amber-800', ring: 'ring-amber-200' },
  { bg: 'bg-rose-100', text: 'text-rose-800', ring: 'ring-rose-200' },
  { bg: 'bg-violet-100', text: 'text-violet-800', ring: 'ring-violet-200' },
  { bg: 'bg-cyan-100', text: 'text-cyan-800', ring: 'ring-cyan-200' },
  { bg: 'bg-orange-100', text: 'text-orange-800', ring: 'ring-orange-200' },
  { bg: 'bg-fuchsia-100', text: 'text-fuchsia-800', ring: 'ring-fuchsia-200' },
];

const UNASSIGNED = { bg: 'bg-zinc-100', text: 'text-zinc-600', ring: 'ring-zinc-200' };

export function ownerColor(userId: string | null | undefined) {
  if (!userId) return UNASSIGNED;
  // Hash uuid into palette index — deterministic per user.
  let h = 0;
  for (let i = 0; i < userId.length; i++) h = ((h << 5) - h + userId.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}
```

Re-usable across contacts list, lead cards, appointments calendar — anywhere an owner avatar wants a colour.

## `appointments-api.service.ts`

- Extend `AppointmentListItem` / `Appointment` with `last_activity_at`.
- Extend `AppointmentListQuery` with `sort`, `order`, `assigned_to_id`, `status`, `scheduled_from`, `scheduled_to`.

## `appointments.page.ts`

Signals:
```typescript
readonly view = signal<'list' | 'calendar'>('list');
readonly sortKey = signal<'scheduled_at' | 'created_at' | 'last_activity_at'>('scheduled_at');
readonly sortOrder = signal<'asc' | 'desc'>('asc');
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
readonly statusFilter = signal<'' | 'scheduled' | 'completed' | 'no_show' | 'cancelled'>('');
readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());
readonly users = toSignal(this.usersDir.list(), { initialValue: [] });
```

## `appointments.page.html`

**Filter row:**
- Status chips: All · Upcoming · Completed · No-show · Cancelled.
  - "Upcoming" = status=scheduled AND scheduled_at >= today.
- Assignee dropdown.
- Scope toggle (My / Team / All).

**List view columns:**
- Customer (existing)
- Scheduled at (sortable)
- **Status** (coloured pill: scheduled=blue, completed=emerald, no_show=amber, cancelled=zinc)
- **Owner** (avatar coloured via `ownerColor()` + name)
- **Last activity** (relative time)
- Actions (existing — open detail / edit)

**Calendar view:**
- Each event div uses `ownerColor(event.assigned_to_id)` for `bg-*` + `text-*` classes.
- Hover tooltip shows Owner name.
- Click event → small popover (built next step) with Reassign / Reschedule / Mark completed / Cancel actions.

## Acceptance

1. List view shows Status, Owner (colour-coded), Last activity columns. Sortable.
2. Status chips filter.
3. Calendar events colour-coded by owner. Unassigned = zinc.
4. Scope toggle works; junior sees only Mine.
5. Assignee dropdown filters list + calendar.

## Lucide icons used

`calendar`, `list`, `users`, `circle-dot`. Standard.

## Self-check vs the 10 rules

- ✅ Rule 8 — 4 files (1 new util, 3 modified). Well under limit.

## Stop-and-report template

> ✅ Step 2 complete.
> **Files changed:** 4.
> **What you can verify:**
> 1. List view: Status / Owner / Last activity columns.
> 2. Calendar view: events coloured by owner.
> 3. Status chips + scope + assignee filters.
> **Tests added:** none (FE smoke).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 3 (reschedule modal + bulk + ergonomics).
