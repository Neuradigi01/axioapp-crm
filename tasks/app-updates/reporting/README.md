# Reporting — Funnel, sales-by-rep, forecasting, dashboards

Composable analytics layer with reusable backend query builders and a frontend widget library. Delivers conversion funnel, sales leaderboard, revenue + pipeline, and forecasting. Widgets plug into a tabbed Reports page AND the main `/user/dashboard` landing so every role sees a relevant default view on login.

## Why this exists

The 2026-06-11 audit named reporting as the second-biggest gap. Today the only report is "workload summary" (open record count per user). Owners and Store Managers cannot answer the basic questions a CRM is supposed to answer:

- How many walk-ins / leads / conversations turn into won sales? (Funnel.)
- Which rep is hitting target? Which lead source converts best? (Leaderboard + attribution.)
- What revenue should we expect to close this month given the current pipeline? (Forecast.)
- How did last week compare to the week before? (Trends.)

Phase 5 has a thin `step-5.5-reporting.md` placeholder, and Phase 5.1 (Admin Dashboard) was deferred because the metric endpoints didn't exist. This track delivers the endpoints + widget library + a Reports page, and the dashboard track can then assemble role-specific landing pages on top.

| Gap | What's missing today |
|---|---|
| **No reusable query builders** | Each module would invent its own SQL otherwise. The reporting layer is the place to centralise. |
| **No date-range filter contract** | Every report needs From/To. No reusable component. |
| **No funnel endpoint** | Walk-in → lead → won conversion is the single most-requested metric for retail. |
| **No sales-by-rep endpoint** | Leaderboard + target % is the second most-requested. |
| **No forecasting** | Pipeline value × stage probability is industry standard; not built. |
| **No widget library** | Reports today would be one-off pages full of hardcoded chart wiring. |
| **No scheduled / emailed reports** | "Email me my Monday morning summary" is a 2026-baseline CRM feature. |
| **No CSV / PDF export** | Reports lock data in the UI. Owners want to send the funnel chart to their accountant. |
| **No caching** | Heavier aggregations recomputed per request would not survive multi-rep load. |

## What this does NOT do

- **Does not build a custom report builder.** Picking columns, GROUP BYs, filters via a drag-and-drop UI is huge. v2.
- **Does not deliver real-time streaming dashboards.** All metrics are point-in-time queries with optional Redis caching. Live sockets are out of scope.
- **Does not handle revenue from billing module.** Reports here read from `won_leads` / `invoices` (furniture pack POS), not from the SaaS subscription billing module — those are different domains.
- **Does not build a separate "Insights" or "BI" surface.** Reports + dashboard widgets only. A future "anomaly detection" or "AI insights" panel is post-v1.
- **Does not touch `features/admin/`.**

## Acceptance criteria

A new Owner, on a fresh org with real data, can:

1. Land on `/user/dashboard` → see role-appropriate widgets pre-populated: KPI tiles (Leads this week, Won this month, Pipeline value, Active conversations), a 30-day revenue line chart, a 4-step funnel, a sales leaderboard for the top 5 reps.
2. Click "Reports" in the sidebar → tabbed Reports page with at least: Sales · Pipeline · Funnel · Staff · Forecast tabs.
3. Date-range picker in the page header (defaulting to "Last 30 days") drives every widget on the page. Switching to "Last 90 days" re-fetches all visible widgets.
4. Funnel tab: visualisation of Walk-in (1042) → Lead (387, 37%) → Quoted (124, 32%) → Won (43, 35%). Drilldown click on any stage → contact-list filtered to those records.
5. Staff tab: leaderboard table with rep, leads handled, won count, won value, target%, trend arrow vs prior period. Click rep → drilldown.
6. Forecast tab: pipeline by stage × stage probability = projected close. Per-month bar chart for the next 3 months. Confidence band based on past 90 days' close-rate variance.
7. Export buttons on every report: PDF and CSV. PDF preserves charts as inline SVG; CSV drops the raw rows.
8. Settings → Scheduled Reports → "Email me a weekly funnel summary on Monday at 9am." Background job sends the PDF to the user every Monday.
9. Sales Executive views the same Reports page but only sees scoped widgets (their own leads, their own deals). Junior Sales Executive sees only their own.
10. RLS: a second org's data never appears in any widget. Redis cache keys are scoped per (org, role, query-hash).

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend: reporting foundation (date-range, query base, RLS, Redis cache)](step-1-backend-reporting-foundation.md) | Pending | ~1 day |
| 2 | [Backend: conversion funnel endpoint (walk-in → lead → quoted → won)](step-2-backend-conversion-funnel.md) | Pending | ~1 day |
| 3 | [Backend: sales-by-rep + leaderboard endpoint with targets](step-3-backend-sales-by-rep.md) | Pending | ~1 day |
| 4 | [Backend: revenue + pipeline value + KPI tile endpoint](step-4-backend-revenue-and-pipeline.md) | Pending | ~1 day |
| 5 | [Backend: forecasting endpoint (pipeline × stage probability)](step-5-backend-forecasting.md) | Pending | ~1 day |
| 6 | [Frontend: widget library (LineChart, BarChart, Funnel, Leaderboard, KPITile, DateRangePicker)](step-6-frontend-widget-library.md) | Pending | ~1.5 days |
| 7 | [Frontend: Reports page with tabbed views + drilldowns + export](step-7-frontend-reports-page.md) | Pending | ~1.5 days |
| 8 | [Frontend: Dashboard integration + role-adaptive defaults + scheduled reports](step-8-frontend-dashboard-integration.md) | Pending | ~2 days |

**Total: ~10 working days.**

## Dependencies

- Phase 2 modules (contacts, leads, pipelines, walk-ins) — query targets.
- Phase 3 modules (calls, conversations, staff, campaigns) — staff leaderboard activity counts.
- Phase 4.X furniture pack billing/POS module — invoices feed revenue widgets.
- Step 5.1 (Admin Dashboard) becomes Step 8 of this track — superseded.
- Step 5.5 (Reporting placeholder in Phase 5) becomes superseded by Steps 1–7 of this track.
- Redis (locked stack) — required for caching.
- Celery beat — required for scheduled report emails.

## File budget

| Area | Files |
|---|---|
| Step 1 (foundation) | 5 new (`core/reporting/{models,schemas,service,router,module,cache}.py` → 6 actually) + 1 modified permissions registry + 1 test |
| Step 2 (funnel) | 1 new (`core/reporting/queries/funnel.py`) + 1 modified router + 1 test |
| Step 3 (sales-by-rep) | 1 new (`core/reporting/queries/sales_by_rep.py`) + 1 modified router + 1 test |
| Step 4 (revenue+pipeline) | 2 new (`core/reporting/queries/{revenue,pipeline}.py`) + 1 modified router + 1 test |
| Step 5 (forecasting) | 1 new (`core/reporting/queries/forecast.py`) + 1 modified router + 1 test |
| Step 6 (widget library) | 12 new — 6 widget component files (.ts/.html each) for LineChart/BarChart/Funnel/Leaderboard/KPITile/DateRangePicker |
| Step 7 (reports page) | 7 new — reports.page (.ts/.html), 5 tab components (Sales/Pipeline/Funnel/Staff/Forecast) + 1 modified routes + 1 modified sidebar registration |
| Step 8 (dashboard + scheduled) | 1 migration (scheduled_reports table) + 5 new (`core/reporting/scheduled.py` + frontend dashboard tiles + settings tab for schedule mgmt) + 1 modified celery beat |

**Total ~40 files across 8 steps, 1 migration.** Largest single step (Step 6 widget library) ships 12 files because the widget set is one logical unit; each widget is small (~30 lines .ts + .html).

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Every report query honours RLS | Step 1 — base query builder always runs inside the per-request `app.org_id` setting; raw SQL parameterised with binds, never string-interpolation. |
| Date-range param contract | Step 1 — `DateRange(start, end)` schema reused by every endpoint. UI passes `?start=ISO&end=ISO`. |
| Permission-scoped queries | Steps 2–5 — every query takes `(org_id, actor)` and applies actor-specific filters (Owner sees all; Sales Executive sees own). |
| Caching keyed per (org, role-scope, query-hash) | Step 1 — `core/reporting/cache.py` SHA256s a stable representation. 60s default TTL; per-query override. |
| All widgets reusable | Step 6 — every widget accepts `(data, options)` and emits drilldown clicks via a single `(drill)` output. |
| `org_id` on `scheduled_reports` table | Step 8 — yes + RLS. |
| `core/` never imports `packs/` | Yes — revenue endpoint reads from `core/billing/invoices` (when present in core) or accepts a pack-contributed query plugin via a registry. |
| Export safety | Step 7 — CSV cells are sanitised (no formula-injection `=cmd`); PDFs render via a sandboxed renderer (`weasyprint` or `playwright`). |
| Audit events | `reports.export.csv`, `reports.export.pdf`, `reports.scheduled.created`, `reports.scheduled.delivered`. |

## Self-check against the 10 rules

- Rule 1: Pure core.
- Rule 2: `scheduled_reports` carries `org_id` + RLS. All query SQL filters by `org_id`.
- Rule 3: Reports can filter / group by `custom_data.<key>` for any entity that supports it. Step 1's query base helper exposes a `custom_field(path)` macro.
- Rule 4: Widget options panels render from a small declarative config — no hardcoded option forms per widget. (Date range picker is the universal one.)
- Rule 5: One new sidebar entry (Reports). Dashboard widgets register themselves via a widget registry contributed by Step 6 so Phase 5.1 can compose them.
- Rule 6: Two new permission keys: `reports.read`, `reports.export`.
- Rule 7: `pack.yaml` unaffected. Pack may later contribute pack-specific queries (e.g. furniture-pack `inventory_turnover`) via the same query registry.
- Rule 8: 40 files across 8 steps. Largest is 12 files (widget library — one logical unit).
- Rule 9: Stop-and-report after each step.
- Rule 10: No TODOs. Caching, exports, scheduled emails all real from day one.

## Operational concerns

- **Cache invalidation.** 60s TTL is short enough that "stale data" is acceptable. No explicit invalidation on writes for v1; a future webhook from contacts/leads write paths can publish bust-events if business demands sub-minute freshness.
- **PDF rendering dependency.** WeasyPrint (preferred — pure Python) needs system fonts available in the container. If the API container is too thin, switch to Playwright (heavier image but more reliable). Decide in Step 7.
- **Scheduled-report timezone handling.** "Monday 9am" needs to honour the org's timezone setting. Store schedules in UTC; cron-tick converts per org. Document in Step 8.
- **CSV formula injection.** Prefix any cell starting with `=`, `+`, `-`, `@` with `'` (Excel/Sheets convention) before write. Already a known pattern; cite OWASP CSV injection guidance in Step 7.

## After this track

- The CRM finally answers the "is this paid effort working?" questions every Owner asks. Demo screenshots become possible.
- Phase 5.1 (Admin Dashboard) becomes a thin assembly task on top of the widget library and dashboard registry from Step 6/8 — collapses from a 5-day estimate to ~1 day.
- The funnel + leaderboard + forecast are the three single-screenshot artefacts most-asked-for by prospects in demos. This unlocks the sales motion.
- Marketing has real attribution: which lead source converts best, which campaign actually paid back.
- The widget library is reusable for future product surfaces — a future customer portal could show the customer's own order funnel using the same Funnel widget.
