# Step 5.1 — Dashboard — admin overview

**Goal:** Build the main dashboard page matching the screenshot — KPI cards, Best Selling chart, Stock Alerts, Recent Leads, Upcoming Appointments, AI Activity Feed (live).
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** most prior modules
**Status:** Pending

## Scope
**In-scope:**
- Backend: `app/core/dashboard/router.py` aggregating widgets:
  - `GET /dashboard/kpis` — today's revenue, today's invoices, walk-ins, leads created.
  - `GET /dashboard/best-selling?period=` — top 5 catalog items by qty sold.
  - `GET /dashboard/stock-alerts` — top 5 alerts.
  - `GET /dashboard/recent-leads` — top 10.
  - `GET /dashboard/upcoming-appointments?days=7`.
  - `GET /dashboard/ai-activity?limit=20` — last AI events (suggestions sent, follow-ups fired, staging jobs done).
- Frontend page replacing the home-stub from 1.9.
- Live AI Activity uses notifications WS.

## Files to touch
- `api/src/app/core/dashboard/{__init__,router,service,module}.py` (created)
- `api/src/app/main.py` (modified)
- `app/src/app/features/user/core/layout/home.component.ts/.html` (modified — full dashboard)
- `app/src/app/features/user/core/dashboard/*` (created — widget components)

## Plan
1. Backend aggregation queries; cache for 30s in Redis to reduce DB load.
2. Frontend dashboard with grid of widgets (signal-based data per widget, refresh every 30s).
3. AI Activity widget subscribes to WS for `ai_*` events and prepends.

## Tests to add
- `tests/test_dashboard.py` — endpoints return shape.

## Verification checklist
**Backend/Frontend:**
- visit `/` → dashboard with all widgets populated.
- generate AI suggestion → activity feed updates live.

## Self-check (10 rules)
- [ ] No hardcoded module list; widgets pull data via well-defined endpoints.
- [ ] Tailwind only.

## Stop & report
This concludes **Phase 5**. Await "proceed" before Step 6.1.
