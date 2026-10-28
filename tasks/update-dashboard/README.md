# Update Dashboard page

A focused track to bring the `/user/dashboard` page up to standard-CRM visual quality — hero KPI strip with period-over-period deltas, trend chart, pipeline funnel chart, quick-actions toolbar, and a date-range picker. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready.

## Why this exists

The dashboard today is a clean v1: greeting, eight (or five) KPI number cards, recent activity list, upcoming appointments list. Permission-gated org-vs-personal scope already differentiates content for the seven roles — Owner / Store Manager / Senior Sales Exec land on the org view, Sales Exec / Junior Sales / Design Consultant / Warehouse Manager land on the personal view. **The data is role-aware; the presentation isn't.**

Compared to a standard generic CRM dashboard (HubSpot, Pipedrive, Zoho, Salesforce) it's missing:

- **Hero KPI strip** — large numbers with delta vs prior period and trend arrows. Today every card is the same flat size.
- **Trend chart** — revenue / pipeline / leads / calls / appointments over time. Today the dashboard shows zero charts.
- **Funnel chart** — visual pipeline stage drop-off. Today the dashboard surfaces "conversion rate" as a single percentage with no breakdown.
- **Quick-actions toolbar** — "New Lead · Log Call · Schedule Meeting · Add Contact" buttons at the top so the dashboard is a launchpad, not a read-only summary.
- **Date-range picker** — every other CRM lets you pivot the dashboard between 7d / 30d / 90d / 365d. Today everything is hard-coded ("today", "this week", "last 30 days").
- **Visual hierarchy** — currently every card has the same weight; the eye has nowhere to land first.

## Standard CRM features added by this track

| Feature | Pattern |
|---|---|
| **Hero KPI tiles** | Top 4 cards rendered large with current value, delta % vs prior period, up/down/flat trend arrow. |
| **Period-over-period deltas** | Every numeric card returns `previous_value` + `delta_pct` + `delta_direction`; tiles show `↑ 12%` / `↓ 4%` / `→` in green/red/zinc. |
| **Revenue / pipeline trend chart** | Line or area chart, last 30/90/365 days, metric selector (leads / pipeline value / calls / appointments). |
| **Pipeline funnel chart** | Horizontal bar / funnel of counts per stage over the selected range, both scopes (team or personal). |
| **Quick-actions row** | Header strip with 4 actions: New Lead · Log Call · Schedule Meeting · Add Contact. Each opens the existing modal. Each button permission-gated. |
| **Date-range picker** | Header control with `7d / 30d / 90d / 365d / Custom`. Drives the trend + funnel widgets. Selection persists per user via `localStorage`. |
| **Polished layout** | Page restructured as: greeting + date-range + refresh → quick-actions → hero KPI strip → charts row → secondary KPI grid → recent activity + upcoming appointments. Tailwind only. |

## What this does NOT do

- **No per-role widget customization** (Option B). The current permission-based org-vs-personal scope already handles role-driven content. Adding role-specific widgets (warehouse stock, design-consultant orders, owner AR) is deferred — most of those are pack-level (furniture), not core.
- **No drag-resize widget grid.** Premature without real-user demand.
- **No AI widgets** (sentiment, next-best-action, summaries). Out of scope per current product direction.
- **No multi-dashboard / saved-dashboard feature.** Single dashboard per user.
- **No widget configurability** (hide/show, reorder). Single fixed layout.
- **No goal/quota setting UI.** Targets exist per-staff in the Staff module; surfacing them as progress rings on the dashboard is a separate track if needed.
- **No backend cache layer.** Existing queries are fast at current data volumes; add Redis caching only if profiling shows a need.

## Acceptance criteria

After this track, any signed-in user opening `/user/dashboard`:

1. **Sees four large hero KPI tiles** at the top with current value, prior-period value, percentage delta, and trend arrow.
2. **Sees a quick-actions row** above the hero tiles (New Lead · Log Call · Schedule Meeting · Add Contact) with each action permission-gated.
3. **Sees a date-range picker** in the header (`7d / 30d / 90d / 365d / Custom`) that drives the trend + funnel widgets.
4. **Sees a trend chart** (line/area) for the selected range, with a metric selector.
5. **Sees a pipeline funnel chart** showing stage drop-off across the selected range.
6. **Still sees the secondary KPI grid, recent activity, and upcoming appointments** — kept from today's layout, repositioned below the new widgets.
7. **Sees content scoped correctly** — org-scope users see team-wide widgets; personal-scope users see only their own data. (No change to existing scope rule.)
8. **Has the same dashboard structure regardless of role** — all seven roles get the same visual layout; content differs only via the existing permission-based scope split.
9. **Sees range selection persist** across page reloads (localStorage).
10. **Sees no flicker on refresh** — each widget loads independently with its own skeleton.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: period-over-period deltas on KPI cards](step-1-backend-kpi-deltas.md) | Pending | ~½ day |
| 2 | [Backend: trend chart endpoint (time-series)](step-2-backend-trend-endpoint.md) | Pending | ~½ day |
| 3 | [Backend: pipeline funnel endpoint](step-3-backend-funnel-endpoint.md) | Pending | ~½ day |
| 4 | [Frontend: chart library + shared date-range picker + KPI tile primitive](step-4-frontend-charts-and-daterange.md) | Pending | ~1 day |
| 5 | [Frontend: Hero KPI strip with deltas](step-5-frontend-hero-kpi-tiles.md) | Pending | ~½ day |
| 6 | [Frontend: Trend chart widget](step-6-frontend-trend-chart-widget.md) | Pending | ~½ day |
| 7 | [Frontend: Funnel chart widget](step-7-frontend-funnel-chart-widget.md) | Pending | ~½ day |
| 8 | [Frontend: Quick-actions row + final dashboard layout](step-8-frontend-quick-actions-and-layout.md) | Pending | ~½ day |

**Total: ~4–5 working days.** Stop and report after each step per Rule 9.

## Dependencies

- Existing dashboard module — backend [api/src/app/core/dashboard/](../../api/src/app/core/dashboard/) and frontend [app/src/app/features/user/core/dashboard/](../../app/src/app/features/user/core/dashboard/). Done.
- `GET /dashboard/summary` — extended in Step 1, kept backward-compatible.
- Permission keys `leads.write`, `calls.write`, `appointments.write`, `contacts.write` — exist. Reused for quick-action button gating.
- Pipeline stage data — exists via [pipelines](../../api/src/app/core/pipelines/) module. Reused for funnel.
- Chart library — **NEW dependency** introduced in Step 4. Recommend [ApexCharts](https://apexcharts.com/) + [ng-apexcharts](https://github.com/apexcharts/ng-apexcharts) (free, MIT, polished defaults, ~50 kB gzipped, works cleanly with Tailwind). Decision locked in Step 4.

## File budget

| Area | Files | Notes |
|---|---|---|
| Step 1 backend | 3 modified (`service.py`, `schemas.py`, `router.py`). | Backward-compatible: existing `value` field stays; new `previous_value`, `delta_pct`, `delta_direction` are additive. |
| Step 2 backend | 3 modified (`service.py`, `schemas.py`, `router.py`). | New endpoint `GET /dashboard/trend`. |
| Step 3 backend | 3 modified (`service.py`, `schemas.py`, `router.py`). | New endpoint `GET /dashboard/funnel`. |
| Step 4 frontend | 2 modified (`package.json`, `app.config.ts`), 3 new shared (`dashboard-date-range.component.ts/html`, `dashboard-kpi-tile.component.ts/html`, `dashboard-range.signal.ts`). | Library install + 2 primitives. |
| Step 5 frontend | 1 modified (`dashboard.page.html`), 1 modified (`dashboard.page.ts`). | Hero strip wires existing summary endpoint. |
| Step 6 frontend | 2 new (`trend-chart.component.ts/html`), 1 modified (`dashboard.page.ts/html`). | ApexCharts line/area. |
| Step 7 frontend | 2 new (`funnel-chart.component.ts/html`), 1 modified (`dashboard.page.ts/html`). | ApexCharts horizontal bar. |
| Step 8 frontend | 2 new (`quick-actions.component.ts/html`), 1 modified (`dashboard.page.ts/html`). | Final layout pass. |
| Tests | Smoke via Ajay's Workspace; minimal pytest for the new endpoints (deltas, trend, funnel). | Smoke target: `41f9ede9-41b3-44ce-b489-3004566d4068`. |

**Total ~26 files across 8 steps.** Each step ≤10 files / ≤400 LOC per Rule 8.

## Invariants this track enforces

| Rule | Where |
|---|---|
| Dashboard remains tenant-scoped | All new queries join through `org_id`; RLS applies. |
| Scope rule unchanged | Org-scope vs personal-scope still driven by `users.read` permission; widgets inherit caller's scope. |
| No role-name branching | Backend and frontend never inspect `role.name`; widget visibility / content gated only by permissions. Rule 6. |
| No pack imports in core | New dashboard widgets stay in `core/dashboard/`; do not import from `packs/furniture/`. Rule 1. |
| Card schema stays open | `DashboardCard` continues to be a generic shape (`key / label / value / format / link`); new fields (`delta_pct` etc.) are additive and optional. Adding a card stays a one-line backend change + (optionally) one new template branch. |
| Tailwind only | All new components use Tailwind; no PrimeNG / Material in the new dashboard widgets. |

## Self-check against the 10 rules

- ✅ Rule 1: `core/dashboard/` adds no `packs/` imports.
- ✅ Rule 2: `org_id` filter on every new query; RLS unchanged.
- ✅ Rule 3: No new custom-field surface; deltas and chart data are computed, not stored.
- ✅ Rule 4: Dashboard does not render forms; not applicable.
- ✅ Rule 5: Sidebar entry unchanged; this track upgrades the destination.
- ✅ Rule 6: No new permission keys; reuses existing `*.write` keys for quick-action gating.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 8 steps; each ≤10 files / ≤400 LOC; each reviewable in ≤30 min.
- ✅ Rule 9: Stop-and-report after each step.
- ✅ Rule 10: No TODOs; each widget ships fully wired, permission-gated, tenant-scoped, and Tailwind-styled.

## After this track

- Dashboard becomes the new pattern reference for charts in this codebase (ApexCharts wrapper conventions, shared date-range pattern, KPI tile primitive).
- Date-range picker primitive is ready to be reused by the Reporting page when that track lands (Phase 5.5 if revived).
- Hero KPI tile primitive is ready to be reused on detail pages (contact / lead detail headers) if added later.
- Trend / Funnel chart components are ready to be reused on the Reporting page.
