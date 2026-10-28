# Step 7 — Frontend: funnel chart widget

**Goal:** Add a funnel widget to the dashboard that calls `/dashboard/funnel` (Step 3), renders an ApexCharts horizontal bar (true "funnel" types in ApexCharts require Pro; the horizontal-bar variant gives the same visual at the free tier), and surfaces won / lost counters alongside.

## Files changed

### New
- `app/src/app/features/user/core/dashboard/widgets/funnel-chart.component.ts`
- `app/src/app/features/user/core/dashboard/widgets/funnel-chart.component.html`

### Modified
- `app/src/app/features/user/core/dashboard/dashboard.page.ts`
- `app/src/app/features/user/core/dashboard/dashboard.page.html`

### Tests
- Manual smoke against Ajay's Workspace.

## `funnel-chart.component.ts`

Standalone, OnPush. Imports `NgApexchartsModule`.

State:

```ts
protected readonly loading = signal(true);
protected readonly error = signal<string | null>(null);
protected readonly data = signal<DashboardFunnelResponse | null>(null);

constructor() {
  effect(() => {
    const r = dashboardRange();
    this.load(r);
  });
}
```

Fetch logic mirrors Step 6's trend component. On success, set `data()`.

Chart series built from `data().stages`:

```ts
protected readonly series = computed(() => {
  const d = this.data();
  if (!d) return [];
  return [{
    name: 'Leads',
    data: d.stages.map(s => ({ x: s.stage_name, y: s.count })),
  }];
});
```

ApexCharts options (horizontal bar configured to read as a funnel):

- `chart.type = 'bar'`
- `chart.toolbar.show = false`
- `plotOptions.bar.horizontal = true`
- `plotOptions.bar.barHeight = '70%'`
- `plotOptions.bar.borderRadius = 4`
- `plotOptions.bar.distributed = true` (each stage its own color)
- `colors = ['#18181b', '#27272a', '#3f3f46', '#52525b', '#71717a', '#a1a1aa']` (zinc ramp; cycles for stages > 6)
- `xaxis.categories = stages.map(s => s.stage_name)`
- `dataLabels.enabled = true`, `dataLabels.style.colors = ['#fff']`
- `legend.show = false`
- `tooltip` shows `% of total = count / totalLeadsInRange * 100`.

## `funnel-chart.component.html`

```html
<div class="rounded-xl border border-zinc-200 bg-white shadow-sm">
  <div class="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
    <h2 class="text-sm font-semibold text-zinc-900">Pipeline funnel</h2>
    @if (data(); as d) {
      <span class="text-xs text-zinc-500">{{ d.total_leads_in_range }} leads in range</span>
    }
  </div>

  <div class="p-4">
    @if (error(); as err) {
      <div class="flex h-64 items-center justify-center text-sm text-rose-700">{{ err }}</div>
    } @else if (loading()) {
      <div class="h-64 animate-pulse rounded bg-zinc-50"></div>
    } @else if (data(); as d) {
      @if (d.stages.length === 0) {
        <div class="flex h-64 items-center justify-center text-sm text-zinc-500">
          No pipeline stages configured.
          <a routerLink="/user/pipelines" class="ml-1 font-medium text-zinc-700 hover:underline">Set up pipeline →</a>
        </div>
      } @else {
        <apx-chart
          [series]="series()"
          [chart]="chart()"
          [plotOptions]="plotOptions()"
          [colors]="colors()"
          [dataLabels]="dataLabels()"
          [xaxis]="xaxis()"
          [legend]="legend()"
          [tooltip]="tooltip()"
          [grid]="grid()" />

        <div class="mt-3 grid grid-cols-2 gap-3 border-t border-zinc-100 pt-3">
          <div class="rounded-lg bg-emerald-50 px-3 py-2 ring-1 ring-emerald-100">
            <div class="text-xs text-emerald-700">Won in range</div>
            <div class="text-lg font-semibold text-emerald-900">{{ d.won_count }}</div>
          </div>
          <div class="rounded-lg bg-rose-50 px-3 py-2 ring-1 ring-rose-100">
            <div class="text-xs text-rose-700">Lost in range</div>
            <div class="text-lg font-semibold text-rose-900">{{ d.lost_count }}</div>
          </div>
        </div>
      }
    }
  </div>
</div>
```

## Page wiring — `dashboard.page.html`

Replace the "funnel chart slot" placeholder added in Step 6 with the real component:

```html
<section class="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
  <app-dashboard-trend-chart />
  <app-dashboard-funnel-chart />
</section>
```

Import `FunnelChartComponent` in `dashboard.page.ts` standalone `imports`.

## Verification checklist

**Frontend (smoke against Ajay's Workspace):**
- Org-scope user opens dashboard → funnel renders with one bar per active pipeline stage, ordered from widest (top) to narrowest (bottom).
- Won / Lost tiles below the chart match the values from `/dashboard/funnel?range=30d`.
- Change the date-range pill → funnel re-fetches and re-renders.
- Personal-scope user → funnel restricted to their leads.
- Empty-pipeline org → empty-state message links to `/user/pipelines`; chart does not render an empty axis.
- No console errors.

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 6: no role-name branching.
- [ ] Rule 8: 2 new + 2 modified ≤350 LOC.
- [ ] Rule 10: no TODOs; loader, error, empty state all explicit; bar colours stable across renders.
- [ ] Tailwind only.
- [ ] Standalone, signals, OnPush.

## Stop & report

Awaiting "proceed" before Step 8.
