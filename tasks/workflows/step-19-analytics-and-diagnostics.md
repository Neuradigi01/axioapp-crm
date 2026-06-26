# Step 19 — Analytics + "why didn't this fire?" diagnostics

**Goal:** Two related surfaces — per-workflow analytics dashboards (enrolled / completed / exited-at-step funnel + goal-conversion rate + send metrics + cost estimate) AND the diagnostics tool ("pick a contact + event, show why this workflow did or didn't fire").
**Status:** Pending
**Depends on:** Step 4 (run + step_run audit rows). Step 11 (goal node tracking). Step 12 (compliance skip-reasons populate step_runs).

---

## Scope

In-scope:

### Analytics (per-workflow dashboard)

- Backend:
  - `core/workflows/analytics.py`:
    - `compute_workflow_metrics(session, *, org_id, workflow_id, since: datetime, until: datetime) -> dict`:
      - Total enrolled (start_run calls).
      - Completed (run.status='completed').
      - Goal-reached (outcome='goal_reached') + conversion rate.
      - Errored.
      - Currently running.
      - Average completion time (started_at → completed_at across completed runs).
      - Per-step funnel: ordered list of `{node_id, label, enrolled_count, completed_count, skipped_count, errored_count}`.
      - Per-step skip-reason breakdown (e.g. node "send.email" had 200 sends + 50 skipped(opt_out) + 5 skipped(frequency_cap)).
      - Send metrics rollup: total sends + breakdown by channel + delivery success rate (when the channel adapter returns it).
      - Estimated cost: `enrolled * workflow.cost_per_run_cents / 100` — for ROI math.
    - `compute_daily_rate(session, *, org_id, workflow_id, days: int) -> list[{date, enrolled, completed, goal_reached}]` — sparkline data.

  - Endpoints:
    - `GET /api/v1/workflows/{id}/analytics?since=&until=` — `workflows.view_analytics`.
    - `GET /api/v1/workflows/{id}/analytics/daily?days=30` — `workflows.view_analytics`.

  - Cached counters: `tbl_workflows.cached_running_count` (5-min beat refresh) + `tbl_workflows.cached_completed_today_count` — the list-page row mini-stats don't issue per-row queries. The full analytics endpoint queries live.

- Frontend:
  - `app/src/app/features/user/core/workflows/analytics/workflow-analytics.page.{ts,html}`:
    - URL `/user/workflows/:id/analytics`.
    - Date-range picker (default: last 30d).
    - Top KPI cards: total enrolled, completed, goal rate, est. ROI.
    - Funnel chart (step-by-step). Click a step → drawer showing the skip-reason breakdown.
    - Daily-rate sparklines (enrolled / completed / goal_reached).
    - Send metrics rollup table.
    - Per-channel breakdown chart.

### Diagnostics — "why didn't this fire?"

- Backend:
  - `core/workflows/diagnostics.py`:
    - `async trace_event_for_contact(session, *, org_id, contact_id, event_type: str, payload: dict | None) -> dict`:
      - Returns a list of `{workflow_id, workflow_name, eligible: bool, reason_if_not_eligible: str, trigger_evaluation: {condition_ast, evaluated_to, paths_used, missing_paths}, re_enrollment_decision: str}` — one entry per workflow that subscribes to that event_type in the org.
      - When `payload` is null, a synthetic payload is built from the contact's data (simulates a fresh event).

  - Endpoint: `GET /api/v1/workflows/diagnostics/trace?contact_id=&event_type=` — `workflows.view_diagnostics`.

- Frontend:
  - `app/src/app/features/user/core/workflows/diagnostics/diagnostics.page.{ts,html}`:
    - URL `/user/workflows/diagnostics`.
    - Contact picker (typeahead).
    - Event type picker (every catalog event).
    - "Run trace" → calls the endpoint → table view of all subscribing workflows with eligibility + reason.
    - Each row click → modal with the trigger condition AST evaluation tree (shows which leaf condition rejected the contact, with the resolved context paths).

### Run-history view (per-run timeline)

- Frontend:
  - `app/src/app/features/user/core/workflows/run-detail.page.{ts,html}`:
    - URL `/user/workflows/runs/:run_id`.
    - Timeline of step_runs in order.
    - Each step: status badge + node label + started_at + duration + payload (resolved action config) + output + skip_reason / error.
    - "Why was this skipped?" expands to show the compliance-decision details for skipped sends.
    - Contact link → contact detail page.

Out of scope:

- Cross-workflow analytics (e.g. "show me all workflows triggered by lead.created and their relative performance") — v2.
- A/B comparison view (Step 18 ships its own).
- Funnel heatmap on the canvas (visualise which nodes drop the most) — v2.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/analytics.py` | **NEW** |
| `API/src/app/core/workflows/diagnostics.py` | **NEW** |
| `API/src/app/core/workflows/router.py` | edit — 3 new endpoints |
| `API/src/app/core/workflows/tasks.py` | edit — beat task to refresh cached counters |
| `API/src/celery/celery_config.py` | edit — `workflows-refresh-cached-counters` at every 5 min |
| `API/src/app/core/workflows/data_access.py` | edit — funnel + daily-rate queries |
| `API/alembic/versions/<ts>_workflow_cached_counters.py` | **NEW** — ALTER ADD COLUMN x2 |
| `APP/src/app/features/user/core/workflows/analytics/workflow-analytics.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/diagnostics/diagnostics.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/core/workflows/run-detail.page.{ts,html}` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — three new routes |
| `API/tests/workflows/test_analytics.py` | **NEW** |
| `API/tests/workflows/test_diagnostics.py` | **NEW** |

**~13 files. ~1100 lines.**

## Plan

1. Cached-counter columns + beat task.
2. Analytics computation + endpoints + funnel query.
3. Diagnostics trace function + endpoint.
4. Frontend pages: analytics, diagnostics, run-detail.
5. Tests: analytics math correct against seeded run data; diagnostics shows the right rejection reason.

## DB changes / migrations

One migration — 2 ALTER ADD COLUMN on `tbl_workflows`. Reversible.

## Tests

15 pytest + 4 Jest cases:

- Analytics: enrolled / completed / goal_reached counts correct against seeded data.
- Conversion rate calculation.
- Funnel returns ordered list of step_runs by node_id.
- Skip-reason breakdown per step.
- Daily-rate aggregation.
- Estimated cost math.
- Cached counters update on beat refresh.
- Diagnostics: trace returns eligibility decision per subscribing workflow.
- Diagnostics: shows which condition AST node rejected.
- Diagnostics: re-enrollment rule blocked → reason='re_enrollment_blocked'.
- Diagnostics with null payload synthesises from contact data.
- Analytics endpoint 403 without view_analytics perm.
- Diagnostics endpoint 403 without view_diagnostics perm.
- (Jest) Analytics page renders KPIs.
- (Jest) Funnel chart click drills into skip-reason.
- (Jest) Diagnostics page calls trace + renders eligibility table.
- (Jest) Run-detail timeline renders all step_runs.

## Smoke

```
1. /user/workflows/{id}/analytics → KPIs show; funnel chart renders.
2. Click step "send.email" → drawer shows skip reasons (e.g. 5 opt_out, 2 frequency_cap).
3. /user/workflows/diagnostics → contact picker → pick Asha → event picker → lead.created → Run.
4. Trace shows 3 workflows subscribe; "New Lead Welcome" eligible; "Hot Lead Nurture" not eligible (lead.score < 75); "Stale Recovery" not eligible (lead too new).
5. Click "Hot Lead Nurture" row → modal shows trigger condition AST + which leaf rejected.
6. /user/workflows/runs/<run_id> → step timeline visible; click a skipped step → shows compliance decision details.
```

## Risks

- Funnel query joins step_runs by node_id across many runs. Index on `(workflow_id, node_id, status)` covers it — confirm via EXPLAIN on a 10K-run workload.
- Diagnostics could expose sensitive contact data — gated on `workflows.view_diagnostics` (not in default Employee role). Operator + Owner only.
- Synthetic payload generation for diagnostics — careful not to leak fields the contact doesn't have or that don't apply to the event type. Mitigation: payload synthesizer uses the same `VARIABLES_BY_EVENT` map from Step 15.

## Self-check (10 rules)

`core/workflows/` + tiny DB extension. ✓ org_id-scoped. ✓ N/A custom fields (used via field paths in conditions but not configured here). ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced (view_analytics + view_diagnostics). pack.yaml untouched. ✓ 13 files / ~1100 lines — large but justified (analytics + diagnostics + run-detail are independent surfaces). Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 19 — Analytics + diagnostics
Files: 13
Verify: analytics dashboard shows KPIs + funnel + sparklines; diagnostics surfaces eligibility decisions per subscribing workflow; run-detail timeline shows per-step status.
Tests: 15 pytest + 4 Jest.
Awaiting "proceed".
```
