# Step 4 — Frontend: chart library + shared date-range picker + KPI tile primitive

**Goal:** Install the chart library, build the two reusable primitives the rest of the dashboard upgrade depends on — a shared date-range picker and a hero KPI tile component — and a small signal-based store for the selected range. No visible changes to the dashboard yet.

## Files changed

### Modified
- `app/package.json` (add `apexcharts` + `ng-apexcharts`)
- `app/src/app/app.config.ts` (provide `NgApexchartsModule` lazily where the chart components use it — but most likely registered per-component since `ng-apexcharts` is standalone-friendly; confirm at implementation)

### New
- `app/src/app/features/user/core/dashboard/shared/dashboard-range.signal.ts`
- `app/src/app/features/user/core/dashboard/shared/dashboard-date-range.component.ts`
- `app/src/app/features/user/core/dashboard/shared/dashboard-date-range.component.html`
- `app/src/app/features/user/core/dashboard/shared/dashboard-kpi-tile.component.ts`
- `app/src/app/features/user/core/dashboard/shared/dashboard-kpi-tile.component.html`

### Tests
- Manual smoke; no Karma additions in this step.

## Library decision — ApexCharts + ng-apexcharts

- MIT license. Stable. Cleanly themeable to match Tailwind palette.
- ~50 kB gzipped runtime. Tree-shakeable per chart type.
- Standalone-component-friendly (Angular 20 compatible).
- Used by HubSpot, Zoho, Pipedrive look-alike examples — gives the "standard CRM" feel out of the box.

Run from `app/`:
```
npm install apexcharts ng-apexcharts
```
Lock the major versions in `package.json` to avoid breaking changes.

## `dashboard-range.signal.ts`

A tiny module exporting a writable signal `dashboardRange` of type `'7d' | '30d' | '90d' | '365d'`, plus a load helper that reads the persisted value from `localStorage` under key `crm.dashboard.range` (default `'30d'`) and a setter that writes back to `localStorage` whenever it changes (effect or wrap in a setter function).

```ts
export type DashboardRange = '7d' | '30d' | '90d' | '365d';
const STORAGE_KEY = 'crm.dashboard.range';
export const dashboardRange = signal<DashboardRange>(loadInitial());
export function setDashboardRange(next: DashboardRange): void {
  dashboardRange.set(next);
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* private mode */ }
}
```

Module-scoped state is acceptable here because the dashboard widgets all live on one route and the signal resets to the persisted value on full reload. If the signal needs to be cross-route shared later, lift it into an injectable service — out of scope for this step.

## `dashboard-date-range.component.*`

A small standalone component:

- Renders a segmented control: `[ 7D | 30D | 90D | 365D ]`.
- Active button is highlighted (Tailwind `bg-zinc-900 text-white`).
- Click sets the value via `setDashboardRange(...)`.
- Reads from `dashboardRange()` for active state.
- No inputs, no outputs — fully self-contained. The signal is the integration point.
- `ChangeDetectionStrategy.OnPush`. Standalone, Tailwind only.

## `dashboard-kpi-tile.component.*`

A standalone component used by the hero strip in Step 5:

Inputs (signal-based):
```ts
@Input({ required: true }) label = '';
@Input({ required: true }) value: number | string = 0;
@Input() format: 'number' | 'currency' | 'percent' = 'number';
@Input() previousValue: number | string | null = null;
@Input() deltaPct: number | null = null;
@Input() deltaDirection: 'up' | 'down' | 'flat' | null = null;
@Input() link: string | null = null;
@Input() loading = false;
```

Render rules:
- Big number (text-3xl semibold).
- Label below in zinc-500 text-xs.
- Delta pill in top-right of the tile:
  - `up` → green pill `↑ 12.3%`
  - `down` → red pill `↓ 4.0%`
  - `flat` → zinc pill `→ 0%`
  - `null` → no pill
- Currency uses `Intl.NumberFormat` with INR default (matches existing dashboard component).
- Percent appends `%`.
- If `link` is set, tile is a `routerLink`; otherwise it's a plain `div`. (Mirrors existing dashboard card pattern.)
- Skeleton state when `loading === true` (animated zinc bars).

No internal data fetching — pure presentation. Step 5 wires it to `/dashboard/summary`.

## Verification checklist

**Frontend:**
- `npm install` succeeds; bundle build (`ng build`) succeeds; bundle size delta visible in build summary.
- Open Storybook-style harness if available, or temporarily drop `<app-dashboard-date-range />` into the dashboard page → segmented control renders, click toggles active state, `localStorage.crm.dashboard.range` updates, reload preserves selection.
- Drop a static `<app-dashboard-kpi-tile label="Test" value="42" format="number" deltaPct="12.3" deltaDirection="up" />` next to it → tile renders with green ↑ pill.
- No console errors. No TypeScript errors. No Tailwind purge regressions on other pages.

After verification, **remove the temporary harness placements** — Step 5 is where the tile + date-range start being used for real.

## Self-check (10 rules)

- [ ] Rule 8: 5 new files + 2 modified; ≤300 LOC total.
- [ ] Rule 10: no TODOs; both primitives ship complete with skeleton + delta + link behaviours; date-range persists across reload from day one.
- [ ] Tailwind only.
- [ ] Standalone components, signals, OnPush.
- [ ] No imports from `packs/`.

## Stop & report

Awaiting "proceed" before Step 5.
