# Step 8 — Frontend: quick-actions row + final dashboard layout

**Goal:** Add the quick-actions toolbar at the top of the dashboard, move the date-range picker into the page header, and lock the final layout. After this step the dashboard reads as a modern, standard-CRM dashboard end-to-end.

## Files changed

### New
- `app/src/app/features/user/core/dashboard/widgets/quick-actions.component.ts`
- `app/src/app/features/user/core/dashboard/widgets/quick-actions.component.html`

### Modified
- `app/src/app/features/user/core/dashboard/dashboard.page.ts`
- `app/src/app/features/user/core/dashboard/dashboard.page.html`

### Tests
- Manual smoke against Ajay's Workspace.

## `quick-actions.component.ts`

Standalone, OnPush. Imports `LucideAngularModule`, `RouterLink`, and `PermissionsService` (the existing service used elsewhere for `*.write` gating).

Action catalogue:

```ts
type QuickAction = {
  key: 'new_lead' | 'log_call' | 'schedule_meeting' | 'add_contact';
  label: string;
  icon: string;          // lucide name
  permission: string;    // e.g. 'leads.write'
  routerLink?: string;   // routes to the page where the existing modal opens via query param
  queryParams?: Record<string, string>;
};

private readonly ACTIONS: QuickAction[] = [
  { key: 'new_lead',         label: 'New lead',         icon: 'Plus',         permission: 'leads.write',        routerLink: '/user/leads',        queryParams: { create: '1' } },
  { key: 'log_call',         label: 'Log call',         icon: 'Phone',        permission: 'calls.write',        routerLink: '/user/calls',        queryParams: { create: '1' } },
  { key: 'schedule_meeting', label: 'Schedule meeting', icon: 'Calendar',     permission: 'appointments.write', routerLink: '/user/appointments', queryParams: { create: '1' } },
  { key: 'add_contact',      label: 'Add contact',      icon: 'UserPlus',     permission: 'contacts.write',     routerLink: '/user/contacts',     queryParams: { create: '1' } },
];

protected readonly visible = computed(() =>
  this.ACTIONS.filter(a => this.perms.has(a.permission)),
);
```

`?create=1` on each destination route opens the existing create modal — the contacts, leads, calls, and appointments pages already accept this convention from elsewhere in the app; double-check by grepping `create=1` before relying on it, and if the pages don't read it yet, add a small `effect()` in each page that reads the query param on init and opens its existing modal. (That add is the only fall-back work this step may need; if the convention already exists, no other-page edits.)

## `quick-actions.component.html`

```html
@if (visible().length > 0) {
  <section class="mb-4 flex flex-wrap gap-2">
    @for (a of visible(); track a.key) {
      <a
        [routerLink]="a.routerLink"
        [queryParams]="a.queryParams"
        class="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-800 shadow-sm transition hover:border-zinc-300 hover:bg-zinc-50">
        <lucide-icon [name]="a.icon" class="h-4 w-4 text-zinc-500"></lucide-icon>
        {{ a.label }}
      </a>
    }
  </section>
}
```

If the caller has no `*.write` permissions at all, the section disappears (no empty bar).

## Page wiring — `dashboard.page.html`

Final layout, top to bottom:

1. **Header row** — greeting + scope pill on the left; date-range picker + refresh button on the right.
2. **Quick-actions row** — when at least one is visible.
3. **Hero KPI strip** — 4 large tiles (Step 5).
4. **Charts row** — Trend + Funnel side-by-side (Steps 6, 7).
5. **Secondary KPI grid** — remaining cards from `secondaryCards()` (Step 5).
6. **Recent activity + Upcoming appointments** — existing two-column row, kept.

Updated header markup:

```html
<header class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
  <div>
    @if (summary(); as s) {
      <h1 class="text-2xl font-semibold text-zinc-900">Welcome back, {{ s.greeting.first_name }}</h1>
      <p class="mt-1 text-sm text-zinc-500">
        {{ s.greeting.role_name || 'Member' }} · {{ s.greeting.org_name }}
        @if (s.scope === 'personal') {
          <span class="ml-2 inline-flex items-center rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600">Showing your data</span>
        } @else {
          <span class="ml-2 inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">Team view</span>
        }
      </p>
    } @else {
      <div class="h-7 w-56 animate-pulse rounded bg-zinc-200"></div>
      <div class="mt-2 h-4 w-40 animate-pulse rounded bg-zinc-100"></div>
    }
  </div>
  <div class="flex items-center gap-2">
    <app-dashboard-date-range />
    <button type="button" (click)="refresh()" [disabled]="refreshing()"
            class="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50">
      {{ refreshing() ? 'Refreshing…' : 'Refresh' }}
    </button>
  </div>
</header>

<app-dashboard-quick-actions />

<!-- Hero KPI strip from Step 5 -->
<!-- Secondary KPI grid (existing, now bound to secondaryCards()) -->
<!-- Charts row from Steps 6 + 7 -->
<!-- Recent activity + Upcoming appointments (existing) -->
```

Import `QuickActionsComponent` in `dashboard.page.ts` standalone `imports`.

## Verification checklist

**Frontend (smoke against Ajay's Workspace):**
- Owner-role user lands on `/user/dashboard`:
  - Header: greeting + role + org + team-view pill on the left; `[7D | 30D | 90D | 365D]` + Refresh on the right.
  - Quick-actions row visible with all four buttons.
  - Hero strip: 4 large tiles with delta arrows.
  - Charts row: Trend (left) + Funnel (right), responsive to date-range changes.
  - Secondary grid + Recent activity + Upcoming appointments still render.
- Junior Sales Exec (no `users.read`):
  - Header: "Showing your data" pill.
  - Quick-actions row shows only the actions the role's permissions allow (typically all four still — adjust the seed if your demo role lacks `appointments.write`).
  - Hero shows personal metrics.
  - Trend + Funnel restricted to personal scope.
- Click each quick-action button → routes to the relevant page; modal opens (via `?create=1`).
- Switch date range → trend + funnel re-fetch live; hero tiles do not change (deltas tied to fixed per-card windows).
- Refresh button reloads `/dashboard/summary` only — trend + funnel re-fetch automatically via their `effect(() => dashboardRange())` dependency on signal changes (independent of the summary refresh).
- No console errors. Mobile (resize to ≤640px): hero strip stacks to single column; charts row stacks; quick-actions wrap.

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 6: quick-action visibility gated by permission, not by role name.
- [ ] Rule 8: 2 new + 2 modified ≤300 LOC.
- [ ] Rule 10: no TODOs; permission gate, empty state, mobile layout all explicit.
- [ ] Tailwind only.
- [ ] Standalone, signals, OnPush, lucide icons via the existing registered set.

## Stop & report

This concludes the **Update Dashboard** track. Awaiting "proceed" before next track.
