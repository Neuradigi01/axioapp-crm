# Step 7 — Frontend: Reports page with tabbed views + drilldowns + export

**Goal:** `/user/reports` page with five tabs (Sales · Pipeline · Funnel · Staff · Forecast) using the widget library. Header has the shared DateRangePicker that drives every widget on every tab. Per-tab "Export PDF" and "Export CSV" buttons.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Step 6 (widgets).

---

## Scope

In-scope:

- `/user/reports` route + sidebar entry.
- `reports.page.ts/.html` — tab shell with the shared DateRangePicker in the header. Tab state in URL fragment (`#tab=sales`).
- Five tab components:
  - `sales-tab` — revenue LineChart (with source-breakdown toggle) + KPI tiles + leaderboard.
  - `pipeline-tab` — pipeline-value BarChart per stage + KPI tile for total pipeline value.
  - `funnel-tab` — Funnel widget + drilldown drawer showing per-stage contact list.
  - `staff-tab` — leaderboard with targets + trend.
  - `forecast-tab` — forecast BarChart per month with low/high band + "configure expected close dates" empty-state when applicable.
- Export buttons per tab:
  - CSV — call `/reports/{report}/export?format=csv` (added to each backend endpoint in this step). Downloads as `reports-{name}-{range}.csv`. Cells sanitised against formula injection.
  - PDF — backend renders via WeasyPrint server-side; download response as `reports-{name}-{range}.pdf`. Includes inline SVG charts.
- Permission gate on the route: `reports.read`. Exports gated additionally by `reports.export`.

Out of scope:

- Custom report builder UI — v2.
- Saved report views — v2 (but DateRangePicker preset choice persists in localStorage).
- Dashboard integration — Step 8.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/reporting/reports.page.ts` | created |
| `app/src/app/features/user/core/reporting/reports.page.html` | created |
| `app/src/app/features/user/core/reporting/tabs/sales-tab.component.ts` | created |
| `app/src/app/features/user/core/reporting/tabs/sales-tab.component.html` | created |
| `app/src/app/features/user/core/reporting/tabs/pipeline-tab.component.ts` | created |
| `app/src/app/features/user/core/reporting/tabs/pipeline-tab.component.html` | created |
| `app/src/app/features/user/core/reporting/tabs/funnel-tab.component.ts` | created |
| `app/src/app/features/user/core/reporting/tabs/funnel-tab.component.html` | created |
| `app/src/app/features/user/core/reporting/tabs/staff-tab.component.ts` | created |
| `app/src/app/features/user/core/reporting/tabs/staff-tab.component.html` | created |
| `app/src/app/features/user/core/reporting/tabs/forecast-tab.component.ts` | created |
| `app/src/app/features/user/core/reporting/tabs/forecast-tab.component.html` | created |
| `app/src/app/features/user/core/reporting/services/export.service.ts` | created |
| `app/src/app/features/user/user.routes.ts` | modified — add `/user/reports` |
| `api/src/app/core/reporting/router.py` | modified — add `?format=csv` and `?format=pdf` to each endpoint |
| `api/src/app/core/reporting/export/csv.py` | created — CSV writer with formula-injection sanitiser |
| `api/src/app/core/reporting/export/pdf.py` | created — WeasyPrint wrapper |
| `api/src/app/core/reporting/templates/report.html` | created — Jinja template that the PDF renderer consumes |
| `api/pyproject.toml` | modified — add `weasyprint` |
| `api/tests/test_reporting_export.py` | created |

**20 files. Split into 7a (frontend tabs + page, ~14 files) and 7b (export backend + frontend export service, ~6 files).**

## Plan (7a — page + tabs)

1. `reports.page`: tab list, URL-fragment driven. Shared `DateRange` signal at the page level; passes into every tab via input. Tab components subscribe and re-fetch.
2. Each tab assembles widgets from Step 6. Funnel tab also mounts a slide-over drawer for drilldown — clicking a funnel stage emits drill, page opens drawer with paginated contact list.
3. Sidebar registration with module descriptor `id='reporting'`, permission `reports.read`.

## Plan (7b — export)

1. Backend CSV: each report query already returns dict rows; CSV writer iterates with formula-injection sanitisation. `Content-Disposition: attachment`.
2. Backend PDF: render the same data into a single Jinja template that includes inline SVG copies of the charts (a small server-side SVG renderer that mirrors the frontend's; about 100 lines). Pipe through WeasyPrint.
3. Frontend `export.service` adds `Authorization` header to a hidden anchor download trigger.

## Tests

- `api/tests/test_reporting_export.py`:
  - CSV download mime + filename correct.
  - Formula-injection guard: row with cell `=1+1` → output cell `'=1+1`.
  - PDF response is `application/pdf`, > 1KB.
- Frontend:
  - `export.service.spec.ts` — wires headers + triggers download.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_export.py -v

cd app
npm run start
# Visit /user/reports
# Switch tabs; each loads fresh data.
# Change date range; every visible widget re-fetches.
# Funnel tab → click "Leads" stage → drawer with contact list.
# Click Export CSV → file downloads, opens in Excel without formula warning popups.
# Click Export PDF → opens with charts inline.
```

## Risks

- **20-file step.** Split as flagged.
- **WeasyPrint in the API container.** Adds ~50MB image size + system font dependencies. If unacceptable, switch to a sidecar `reports-renderer` container reachable over HTTP. Document trade-off.
- **Server-side SVG rendering parity.** Frontend SVG and PDF SVG must look the same. Easiest path: backend SVG renderer reads the same JSON the frontend widget consumes and produces equivalent output via a tiny shared lib. Worth a 1-page design note.
- **CSV row size for large funnels.** Drilldown CSVs could be 100K rows. Stream via `StreamingResponse` to avoid memory pressure.

## Rollback

Delete files. Revert routes + backend router + pyproject. Sidebar loses the Reports entry. Backend endpoints still work via direct API call.
