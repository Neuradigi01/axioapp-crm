# Step 5 — Frontend: Hero KPI strip with deltas

**Goal:** Replace the top of the dashboard with a hero strip of four large KPI tiles that surface the most important metrics with period-over-period deltas. Keep the existing card grid below as the secondary KPI row.

## Files changed

### Modified
- `app/src/app/features/user/core/dashboard/dashboard.page.ts`
- `app/src/app/features/user/core/dashboard/dashboard.page.html`

### Tests
- Manual smoke against Ajay's Workspace.

## Selection of hero metrics

The hero strip shows four tiles. Which four depends on scope (already returned in the existing payload):

| Scope | Hero tiles (in order) |
|---|---|
| `org` | `leads.pipeline_value` → `leads.new_today` → `appointments.today` → `conversion.rate` |
| `personal` | `leads.my_count` → `tasks.my_open` → `appointments.my_today` → `conversion.my_rate` |

Implementation: a small `HERO_KEYS` map keyed by scope. The hero strip picks cards by `card.key` from the existing `summary().cards` array; if any key isn't present, that tile slot is hidden (graceful degradation, no broken layout).

The cards used by the hero strip are also filtered *out* of the secondary grid below to avoid showing the same metric twice. The remaining `summary().cards` render in the existing 4-column grid as today.

## Page component — `dashboard.page.ts`

Add:

```ts
private readonly HERO_KEYS: Record<'org' | 'personal', string[]> = {
  org: ['leads.pipeline_value', 'leads.new_today', 'appointments.today', 'conversion.rate'],
  personal: ['leads.my_count', 'tasks.my_open', 'appointments.my_today', 'conversion.my_rate'],
};

protected readonly heroCards = computed(() => {
  const s = this.summary();
  if (!s) return [];
  const keys = this.HERO_KEYS[s.scope] ?? [];
  return keys
    .map(k => s.cards.find(c => c.key === k))
    .filter((c): c is DashboardCard => !!c);
});

protected readonly secondaryCards = computed(() => {
  const s = this.summary();
  if (!s) return [];
  const heroKeys = new Set(this.HERO_KEYS[s.scope] ?? []);
  return s.cards.filter(c => !heroKeys.has(c.key));
});
```

The `DashboardCard` interface in the component already needs the three new delta fields from Step 1:

```ts
interface DashboardCard {
  key: string;
  label: string;
  value: number | string | LeaderboardEntry[];
  format: 'number' | 'currency' | 'percent' | 'text' | 'leaderboard';
  link: string | null;
  previous_value?: number | string | null;
  delta_pct?: number | null;
  delta_direction?: 'up' | 'down' | 'flat' | null;
}
```

Import `DashboardKpiTileComponent` and add it to the standalone `imports` array. Also import `computed`.

## Page template — `dashboard.page.html`

Insert a new section **above** the existing KPI grid:

```html
<!-- Hero KPI strip -->
@if (summary(); as s) {
  <section class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
    @for (card of heroCards(); track card.key) {
      <app-dashboard-kpi-tile
        [label]="card.label"
        [value]="card.value"
        [format]="card.format"
        [previousValue]="card.previous_value ?? null"
        [deltaPct]="card.delta_pct ?? null"
        [deltaDirection]="card.delta_direction ?? null"
        [link]="card.link"
      />
    }
  </section>
} @else {
  <section class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
    @for (i of [1,2,3,4]; track i) {
      <div class="h-28 animate-pulse rounded-xl border border-zinc-200 bg-zinc-50"></div>
    }
  </section>
}
```

Change the existing KPI grid loop to iterate `secondaryCards()` instead of `s.cards` so hero metrics don't double-render. Also visually downsize the secondary grid (`gap-3`, the existing 4-col layout, smaller value text in cards) — already the case today, no template churn needed beyond the loop swap.

## Verification checklist

**Frontend (smoke against Ajay's Workspace `41f9ede9-…`):**
- Log in as an Owner-role user → top of dashboard shows 4 hero tiles with currency (pipeline), number (leads today), number (today's appts), percent (conversion). Each tile carries either a green ↑ pill, red ↓ pill, or zinc → pill.
- Hero tiles match the values of the corresponding cards in the existing grid; secondary grid below no longer shows those four.
- Log in as a Junior Sales Exec → hero shows personal metrics (my leads / my open tasks / my appts today / my conversion). No 500s; layout intact.
- Click a hero tile → routes to the linked page (`/user/leads`, `/user/tasks`, etc.) — works as in the existing card behaviour.
- Refresh button still triggers a full reload of all summary data.
- No console errors.

## Self-check (10 rules)

- [ ] Rule 6: no role-name branching — hero key selection uses `scope` (permission-derived), not `role.name`.
- [ ] Rule 8: 2 files modified, ≤150 LOC.
- [ ] Rule 10: no TODOs; missing hero keys degrade gracefully (slot hidden), not crashes.
- [ ] Tailwind only.
- [ ] Standalone, signals, OnPush, `computed` for derived state.

## Stop & report

Awaiting "proceed" before Step 6.
