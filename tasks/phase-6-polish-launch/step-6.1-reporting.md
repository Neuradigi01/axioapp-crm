# Step 6.1 — Reporting/Analytics depth

**Goal:** Reusable analytics widgets for sales, inventory turnover, staff performance, conversion funnels. Date-range filters everywhere.
**Phase:** 6
**Depends on:** most prior modules
**Status:** Pending

## Scope
**In-scope:**
- Backend: `app/core/reporting/`:
  - `service.py` with composable query builders for: sales (revenue by day/week/month, by channel, by category), inventory (turnover, dead stock, ABC), staff (leaderboard with target%), conversion funnel (walk-in → lead → won).
  - Endpoints `/reports/*` with date-range params and drilldown.
- Frontend: `app/src/app/features/user/core/reporting/`:
  - `reports.page.ts/.html` — tabbed report view.
  - Reusable widgets `<report-line-chart>`, `<report-bar-chart>`, `<report-funnel>`, `<report-leaderboard>`.
  - Date-range picker reusable across pages (sticky in header for context).
- Tailwind only.

**Out of scope:**
- Custom report builder UI — out of scope.

## Files to touch
- `api/app/core/reporting/{__init__,service,router,module}.py` (created)
- `app/src/app/features/user/core/reporting/*` (created)

## Plan
1. Backend service uses raw SQL with parameterized binds for performance; falls back to ORM where simple enough.
2. Frontend widgets accept `(data, options)`.
3. Add caching (Redis, 60s) for heavier queries.

## Tests to add
- `tests/test_reports_*.py` — schema + RLS isolation.

## Verification checklist
**Backend/Frontend:**
- visit `/reports` → tabs render data.
- change date range → all widgets re-fetch with new range.

## Self-check (10 rules)
- [ ] Widgets reusable; no per-page duplication.

## Stop & report
Await "proceed" before Step 6.2.
