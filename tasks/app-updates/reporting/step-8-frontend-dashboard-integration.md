# Step 8 — Frontend: Dashboard integration + role-adaptive defaults + scheduled reports

**Goal:** `/user/dashboard` becomes a real landing page assembled from the widget library + a default-widget-set per role. Owner sees one mix, Sales Executive another. Plus: "Email me this report on a schedule" UX backed by a `scheduled_reports` table + Celery beat.
**Track:** App Updates → Reporting
**Status:** Pending — supersedes Phase 5.1 (Admin Dashboard).
**Depends on:** Steps 6, 7.

---

## Scope

In-scope:

- Dashboard widget assembly:
  - `dashboard.page.ts/.html` (replaces the current welcome page) — uses `widget-registry` from Step 6 + a per-role default-widget config to render a 12-column grid.
  - Default configs (per role):
    - **Owner / Store Manager**: 4 KPI tiles (Leads this week, Won this month, Pipeline value, Active conversations) + revenue LineChart + Funnel + Leaderboard top-5.
    - **Senior Sales Executive**: 3 KPI tiles (My leads, My won, My pipeline) + my-revenue LineChart + my-tasks-due-today + my-appointments-today.
    - **Sales Executive / Junior Sales**: 2 KPI tiles (My leads, My won) + my-tasks-due-today + my-appointments-today.
    - **Design Consultant**: my-appointments-this-week + my-tasks-due-today.
    - **Warehouse Manager**: low-stock items + custom-orders due this week (these widgets are pack-contributed via the registry — pack hooks into Step 6's `widget-registry`).
- `dashboard-config.service.ts` — reads role from current user; returns the right widget list. v1 = config in code; v2 = user-customisable layouts.
- Scheduled reports:
  - Alembic migration adding `scheduled_reports` table.
  - `core/reporting/scheduled.py` — Celery beat tick every minute scanning for due schedules; calls the PDF export pipeline; emails the PDF via the existing email backend (replaces LogEmailBackend per Phase 5.11).
  - Settings tab `email-scheduled-reports` — list/create/delete schedules. Form: name, report (Sales/Pipeline/Funnel/Staff/Forecast), cadence (daily / weekly / monthly), time, day-of-week or day-of-month, recipients (emails — defaults to self).
  - Audit events: `reports.scheduled.created`, `reports.scheduled.updated`, `reports.scheduled.deleted`, `reports.scheduled.delivered`.

Out of scope:

- Drag-to-rearrange dashboard layout — v2.
- Per-user custom default widget set — v2.
- Slack / Teams delivery of scheduled reports — v2.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_scheduled_reports.py` | created |
| `api/src/app/core/reporting/scheduled.py` | created — Celery task + model + schema + service in one file (small enough) |
| `api/src/app/core/reporting/router.py` | modified — add `/scheduled-reports` CRUD endpoints |
| `api/src/app/core/celery.py` | modified — add beat schedule entry |
| `api/tests/test_reporting_scheduled.py` | created |
| `app/src/app/features/user/core/dashboard/dashboard.page.ts` | modified — replace placeholder content |
| `app/src/app/features/user/core/dashboard/dashboard.page.html` | modified — render widget grid |
| `app/src/app/features/user/core/dashboard/services/dashboard-config.service.ts` | created |
| `app/src/app/features/user/core/settings/scheduled-reports/scheduled-reports-tab.component.ts` | created |
| `app/src/app/features/user/core/settings/scheduled-reports/scheduled-reports-tab.component.html` | created |
| `app/src/app/features/user/core/settings/scheduled-reports/schedule-edit-modal.component.ts` | created |
| `app/src/app/features/user/core/settings/scheduled-reports/schedule-edit-modal.component.html` | created |
| `app/src/app/features/user/core/reporting/services/scheduled-reports-api.service.ts` | created |
| `app/src/app/features/user/core/settings/settings-page.component.ts` | modified — register tab |
| `app/src/app/app.config.ts` | modified — register lucide icons (`calendar-clock`, `send`) |

**15 files, 1 migration.** Splits into 8a (dashboard, ~3 files) and 8b (scheduled, ~12 files).

## Plan (8a — dashboard)

1. `dashboard-config.service` returns a per-role array of `WidgetSpec`: `{key: 'kpi-tile', endpoint: '/reports/kpis', field: 'leads_this_week', size: 'sm'}`.
2. `dashboard.page` iterates the spec; for each, looks up the component via `widget-registry`, instantiates with the params.
3. Grid layout via Tailwind `grid grid-cols-12` with per-size col-spans (sm = 3, md = 6, lg = 12).
4. Skeleton loading state while widget data fetches.

## Plan (8b — scheduled reports)

1. Migration: `scheduled_reports` table (`id`, `org_id`, `name`, `report_key`, `cadence`, `day_of_week`, `day_of_month`, `hour`, `minute`, `timezone`, `recipients` text[], `last_run_at`, `next_run_at`, `created_by`, `is_active`, `created_at`, `deleted_at`). RLS.
2. Service + router for CRUD.
3. Celery beat task `tick_scheduled_reports` every minute: pick due rows (`next_run_at <= now`), render PDF via Step 7's pipeline, email via real backend, update `last_run_at` + recompute `next_run_at`.
4. Settings tab: list + create/edit modal + delete. Owner can manage all org schedules; reps manage their own.
5. Email subject template: `[CRM] Your {{ report_name }} report — {{ date }}`. Body: small recap + attached PDF.

## Tests

`api/tests/test_reporting_scheduled.py`:

- **Schedule creation:** persists, next_run_at computed correctly.
- **Tick fires due schedules:** mock PDF + email; verify call; `last_run_at` + `next_run_at` advance.
- **Tick skips inactive:** `is_active=false` → skipped.
- **Timezone respect:** schedule with `timezone='Asia/Kolkata'` at 9am Asia/Kolkata → computed `next_run_at` in UTC offset back.
- **Weekly cadence advances by 7 days; monthly by 1 month; daily by 1 day.**
- **RLS:** Org A's schedules invisible to Org B.

## Smoke

```powershell
docker exec template_api-api-1 uv run alembic upgrade head
docker exec template_api-api-1 uv run pytest tests/test_reporting_scheduled.py -v

cd app
npm run start

# Login as Owner → land on /user/dashboard → see widget grid populated
# Login as Sales Executive → land on dashboard → see scoped subset
# Visit /user/settings/scheduled-reports → create "Weekly funnel" Monday 9am
# (Manually advance beat or wait until Monday) → email arrives with PDF
```

## Risks

- **Per-role config drift.** When roles change, the dashboard-config service needs updating. Mitigation: write a small unit test that asserts every role in `permissions.registry` has a matching dashboard config entry.
- **Celery beat-tick load.** 1-minute tick across orgs scanning every schedule. At 10K orgs × 5 schedules each = 50K rows scanned per minute. Easy with a `next_run_at` index. Confirmed by test.
- **PDF rendering on the worker.** Same WeasyPrint dependency as Step 7. Lives in the worker image.
- **Email delivery for scheduled reports requires real SMTP.** Phase 5.11 is the official cutover from `LogEmailBackend`. Document that scheduled reports will only deliver after Phase 5.11. Schedules created earlier persist and start delivering once SMTP lands.
- **Per-row TZ math edge cases.** DST in some orgs' timezone could nudge "9am Monday" by an hour. Use `zoneinfo` (3.13 stdlib), not `pytz`.

## Rollback

`alembic downgrade -1`. Delete files. Revert celery + routes + settings registry + dashboard page. Dashboard reverts to welcome page; in-flight schedules silently stop. Existing scheduled rows preserved by migration if downgrade is partial — document that rollback path.
