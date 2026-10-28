# Step 6 — Frontend: widget library (LineChart, BarChart, Funnel, Leaderboard, KPITile, DateRangePicker)

**Goal:** Six reusable Tailwind + signals components that the Reports page and Dashboard assemble into views. Each widget accepts `(data, options)`, handles its own loading + error + empty states, and emits a single `(drill)` event for drilldowns.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Steps 1–5 (backend endpoints).

---

## Scope

In-scope widgets (six):

1. `<report-kpi-tile>` — single big-number card with label + trend pill (↑12% green / ↓3% red / new).
2. `<report-line-chart>` — time-series. Renders SVG natively (no library) for v1; multi-series support; legend; hover tooltip.
3. `<report-bar-chart>` — categorical bars; horizontal or vertical; per-bar color via options.
4. `<report-funnel>` — funnel visual with per-stage % overlay + drilldown click per stage.
5. `<report-leaderboard>` — sortable table with avatar / name / metric columns + target-progress bar.
6. `<report-date-range-picker>` — From / To inputs + preset buttons (Today, Last 7d, Last 30d, This month, Last month, Last quarter, Custom). Emits `DateRange`.

Shared:

- `widget-base.component.ts` — abstract base for loading/error/empty states + caching key.
- `widget-registry.service.ts` — `register(key, component)` so future widgets / pack-contributed widgets can compose into the dashboard (used in Step 8).
- `report-data-loader.service.ts` — small wrapper around HttpClient with the retry interceptor + a debounced re-fetch when DateRange changes.

Style:

- Tailwind only. No charting library (D3, Chart.js, ngx-charts) — for v1 a hand-rolled SVG renderer keeps the bundle thin and avoids dependency drift. Document: when a widget's complexity outgrows hand-rolled SVG (Sankey, heat-map), reach for `apache-echarts` then.
- Light + dark themes via CSS variables defined in the existing theme system.

Out of scope:

- Cohort widget, heat-map, Sankey — v2.
- Real-time / socket-driven widgets — v2.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/reporting/widgets/kpi-tile.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/kpi-tile.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/line-chart.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/line-chart.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/bar-chart.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/bar-chart.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/funnel.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/funnel.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/leaderboard.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/leaderboard.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/date-range-picker.component.ts` | created |
| `app/src/app/features/user/core/reporting/widgets/date-range-picker.component.html` | created |
| `app/src/app/features/user/core/reporting/widgets/widget-base.component.ts` | created |
| `app/src/app/features/user/core/reporting/services/widget-registry.service.ts` | created |
| `app/src/app/features/user/core/reporting/services/report-data-loader.service.ts` | created |
| `app/src/app/features/user/core/reporting/services/reporting-api.service.ts` | created — typed clients for the 5 backend endpoints |
| `app/src/app/app.config.ts` | modified — register lucide icons (`trending-up`, `trending-down`, `bar-chart-3`, `pie-chart`, `users-round`) |

**17 files.** Exceeds rule-8 ceiling. **Split into 6a (KPI tile + LineChart + BarChart + DateRangePicker + base + services, ~12 files) and 6b (Funnel + Leaderboard + registry wire-up, ~5 files).**

## Plan (6a — basic widgets + plumbing)

1. `widget-base`: abstract `WidgetBase` with signals: `data`, `loading`, `error`. Inputs: `endpoint`, `params`. Template: render `<ng-content>` only when not loading + no error; else show spinner / error / empty.
2. `report-data-loader`: HttpClient wrapper. Manages a cache map by `(endpoint, params)` to avoid duplicate calls when 3 widgets share a date range.
3. `reporting-api.service`: typed `kpis()`, `revenue(params)`, `pipelineValue()`, `salesByRep(params)`, `forecast(params)`, `funnel(params)` calls.
4. `kpi-tile`: takes `value: signal<KPITile>`. Renders big number + trend pill.
5. `line-chart`: takes `series: TimeSeriesResponse[]`. Renders SVG with axis labels, gridlines, multi-color lines, hover overlay.
6. `bar-chart`: same.
7. `date-range-picker`: signal-driven; emits `DateRange` on change; preset buttons.

## Plan (6b — funnel + leaderboard + registry)

1. `funnel`: 4 stacked bars + per-stage % overlay + conversion arrow between stages. Click → emit `(drill)`.
2. `leaderboard`: sortable table component. Built-in column-header click reorders; target-progress bar uses CSS only.
3. `widget-registry`: `register(key, factory)` + `get(key)`. Dashboard composes by key in Step 8.

## Tests

Per-widget unit tests are overkill for v1 — visual review covers the SVG. Service tests:

- `reporting-api.service.spec.ts` — HTTP wiring for all 6 endpoints.
- `report-data-loader.service.spec.ts` — caches calls, dedupes simultaneous requests for same params.
- `widget-registry.service.spec.ts` — register + get.

## Smoke

```powershell
cd app
npm run start

# Build a tiny harness page (`/user/dev/widgets-demo` — already a dev-only route pattern) that mounts each widget with mocked data.
# Visit and visually confirm:
# - KPI tile shows value + trend pill
# - LineChart renders multi-series with legend
# - BarChart correct values
# - Funnel renders 4 stages with conversion %
# - Leaderboard table with sortable headers + target-bar
# - DateRangePicker preset buttons + custom range emits correctly
```

## Risks

- **17-file step.** Split as flagged.
- **SVG renderer footguns.** Axis labelling, log scales, negative values — hand-rolled SVG can produce surprising results. Mitigation: limit v1 to linear positive series; document that when negative values appear, the chart clamps to 0 and shows a warning. Negative is rare in CRM metrics anyway.
- **Lucide icons.** Per the registry rule, the 5 new icons must be added in `app.config.ts`.
- **Responsive sizing.** SVG inside flex containers needs `viewBox` + `preserveAspectRatio` set right. Test on narrow viewport.

## Rollback

Delete files. Revert app.config.ts icon additions. Step 7 (Reports page) cannot land without these.
