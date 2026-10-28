# Step 6 — Frontend: trend chart widget

**Goal:** Add a trend chart component to the dashboard that calls `/dashboard/trend` (Step 2 endpoint), renders an ApexCharts area line, and lets the user switch between the four metrics. Reacts live to the shared `dashboardRange` signal from Step 4.

## Files changed

### New
- `app/src/app/features/user/core/dashboard/widgets/trend-chart.component.ts`
- `app/src/app/features/user/core/dashboard/widgets/trend-chart.component.html`

### Modified
- `app/src/app/features/user/core/dashboard/dashboard.page.ts`
- `app/src/app/features/user/core/dashboard/dashboard.page.html`

### Tests
- Manual smoke against Ajay's Workspace.

## `trend-chart.component.ts`

Standalone, OnPush. Imports `NgApexchartsModule` from `ng-apexcharts`.

State:

```ts
type TrendMetric = 'leads_created' | 'pipeline_value' | 'calls' | 'appointments';
private readonly METRICS: { key: TrendMetric; label: string }[] = [
  { key: 'leads_created',  label: 'Leads created' },
  { key: 'pipeline_value', label: 'Pipeline value' },
  { key: 'calls',          label: 'Calls' },
  { key: 'appointments',   label: 'Appointments' },
];

protected readonly metric = signal<TrendMetric>('leads_created');
protected readonly loading = signal(true);
protected readonly error = signal<string | null>(null);
protected readonly series = signal<{ name: string; data: { x: string; y: number }[] }[]>([]);
```

Fetch logic:

```ts
constructor() {
  effect(() => {
    const m = this.metric();
    const r = dashboardRange();
    this.load(m, r);
  });
}

private load(metric: TrendMetric, range: DashboardRange): void {
  this.loading.set(true);
  this.error.set(null);
  this.http.get<DashboardTrendResponse>(
    `${environment.apiBaseUrl}/dashboard/trend`,
    { params: { metric, range } },
  ).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
    next: (res) => {
      this.series.set([{
        name: this.METRICS.find(x => x.key === metric)!.label,
        data: res.points.map(p => ({ x: p.date, y: p.value })),
      }]);
      this.loading.set(false);
    },
    error: (err) => {
      this.error.set(extractApiError(err) ?? "Couldn't load trend.");
      this.loading.set(false);
    },
  });
}
```

ApexCharts options (kept in component as a computed signal so the chart re-renders when the metric changes):

- `chart.type = 'area'`
- `chart.toolbar.show = false`
- `chart.zoom.enabled = false`
- `stroke.curve = 'smooth'`
- `stroke.width = 2`
- `dataLabels.enabled = false`
- `fill.type = 'gradient'`, `fill.gradient.opacityFrom = 0.4`, `opacityTo = 0.05`
- `colors = ['#18181b']` (zinc-900 for ink) — single-tone, premium feel
- `xaxis.type = 'datetime'`
- `yaxis.labels.formatter = (v) => metric == 'pipeline_value' ? Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(v) : Math.round(v).toString()`
- `tooltip.theme = 'light'`

## `trend-chart.component.html`

```html
<div class="rounded-xl border border-zinc-200 bg-white shadow-sm">
  <div class="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
    <h2 class="text-sm font-semibold text-zinc-900">Trend</h2>
    <div class="flex items-center gap-1">
      @for (m of METRICS; track m.key) {
        <button
          type="button"
          (click)="metric.set(m.key)"
          class="rounded-md px-2 py-1 text-xs font-medium"
          [class]="metric() === m.key
            ? 'bg-zinc-900 text-white'
            : 'text-zinc-600 hover:bg-zinc-100'">
          {{ m.label }}
        </button>
      }
    </div>
  </div>

  <div class="p-4">
    @if (error(); as err) {
      <div class="flex h-64 items-center justify-center text-sm text-rose-700">{{ err }}</div>
    } @else if (loading()) {
      <div class="h-64 animate-pulse rounded bg-zinc-50"></div>
    } @else {
      <apx-chart
        [series]="series()"
        [chart]="chart()"
        [stroke]="stroke()"
        [fill]="fill()"
        [colors]="colors()"
        [xaxis]="xaxis()"
        [yaxis]="yaxis()"
        [dataLabels]="dataLabels()"
        [tooltip]="tooltip()"
        [grid]="grid()" />
    }
  </div>
</div>
```

Each chart option is exposed as a small `computed` signal in the component (`chart()`, `stroke()`, etc.) so the chart re-renders when the metric changes without manual `update` calls.

## Page wiring — `dashboard.page.html`

Insert between the secondary KPI grid and the existing Recent activity / Upcoming appointments row:

```html
<section class="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
  <app-dashboard-trend-chart />
  <!-- funnel chart slot from Step 7 -->
</section>
```

Import `TrendChartComponent` in `dashboard.page.ts` standalone `imports`.

## Verification checklist

**Frontend (smoke against Ajay's Workspace):**
- Org-scope user opens dashboard → trend chart loads with last 30 days of `leads_created`.
- Click each of the 4 metric buttons → chart re-fetches and re-renders with the new metric / formatter.
- Change date-range pill (from Step 4 — when wired into header in Step 8, or temporarily next to the trend chart for smoke) → trend chart re-fetches with the new range.
- Personal-scope user → trend chart loads but values restricted to their data.
- Loading state shows skeleton, error state shows rose-themed message; both look clean.
- No console errors. Bundle includes ApexCharts in the dashboard chunk only (route-level lazy works).

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 6: no role-name branching; scope-blind component.
- [ ] Rule 8: 2 new + 2 modified ≤350 LOC.
- [ ] Rule 10: no TODOs; chart, loader, error all ship together.
- [ ] Tailwind only; chart styling via ApexCharts options, not CSS overrides.
- [ ] Standalone, signals, OnPush, `effect()` for fetch-on-deps.

## Stop & report

Awaiting "proceed" before Step 7.
