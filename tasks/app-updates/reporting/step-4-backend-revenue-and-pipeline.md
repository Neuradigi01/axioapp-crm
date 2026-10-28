# Step 4 — Backend: revenue + pipeline value + KPI tile endpoint

**Goal:** Three endpoints powering the top-of-page KPI tiles and the trend charts: revenue time-series (won deals by day/week/month), pipeline value snapshot (sum by stage), and a small KPI tile bundle (Leads this week, Won this month, Pipeline value, Active conversations).
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Step 1 (foundation), Step 3 (won_value pattern reused).

---

## Scope

In-scope:

- `core/reporting/queries/revenue.py`:
  - `revenue_series(session, org_id, date_range, granularity)` → `TimeSeriesResponse`:
    ```python
    {
      "granularity": "day",
      "points": [
        {"t": "2026-05-12", "value": 87000, "count": 2},
        ...
      ],
      "total_value": 412000,
      "total_count": 17
    }
    ```
  - Source-breakdown variant `?breakdown=source` returns one series per `lead.source`.
- `core/reporting/queries/pipeline.py`:
  - `pipeline_value(session, org_id, scope)` → list of `{stage_key, stage_label, lead_count, value_sum, probability_pct}`.
  - Read stage probabilities from `pipeline_stages.probability_pct` (added if not present; otherwise default 0/25/50/75/100 by stage order).
- KPI bundle endpoint `GET /reports/kpis?as_of=ISO` — single JSON with:
  ```python
  {
    "leads_this_week": {"value": 24, "trend_pct": 8.0},
    "won_this_month": {"value": 12, "trend_pct": -3.2},
    "pipeline_value_inr": {"value": 2850000, "trend_pct": 11.4},
    "active_conversations": {"value": 19, "trend_pct": null}
  }
  ```
- Cached (TTL 60s for series, 30s for KPI tiles which feel more "live").

Out of scope:

- Cohort analysis — v2.
- Per-region revenue split — v2.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/reporting/queries/revenue.py` | created |
| `api/src/app/core/reporting/queries/pipeline.py` | created |
| `api/src/app/core/reporting/router.py` | modified — add `/revenue`, `/pipeline-value`, `/kpis` |
| `api/alembic/versions/0XXX_add_pipeline_stage_probability.py` | created — only if `pipeline_stages.probability_pct` doesn't already exist (check first) |
| `api/tests/test_reporting_revenue_and_pipeline.py` | created |

**5 files. 1 conditional migration.**

## Plan

1. Revenue series: SQL with `date_trunc('day'|'week'|'month', won_at) AS bucket`, sum(value), group by bucket. Backfill empty buckets in Python so the response always has a contiguous series (charts hate missing days).
2. Source breakdown: same SQL grouped also by `source`.
3. Pipeline value: SQL joining `leads` + `pipeline_stages`. Stage probability defaults to 100 for "won" stages, 0 for "lost" stages, else the row value.
4. KPI bundle: 4 small queries via `asyncio.gather`. Trend = same window length shifted back, ((current - prior) / prior) * 100; `null` when prior is 0.
5. Migration: check whether `pipeline_stages.probability_pct` exists from any prior step; only add if missing. Defaults to NULL.

## Tests

`api/tests/test_reporting_revenue_and_pipeline.py`:

- **Revenue series day granularity:** 7 days, 3 days with wins. Series has 7 points, 3 non-zero.
- **Revenue source breakdown:** 4 won deals across 2 sources → 2 series.
- **Pipeline value:** 3 stages, leads spread across them, value_sum correct per stage.
- **KPI bundle:** all 4 tiles populated; trend pct correct.
- **Trend null when prior zero:** new org → all tiles trend=null.
- **Date-range honoured:** widen range to 60 days → won_count higher.
- **RLS isolation:** verified across queries.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_revenue_and_pipeline.py -v

curl "http://localhost:8000/api/v1/reports/kpis" -H "Authorization: Bearer $token"
curl "http://localhost:8000/api/v1/reports/revenue?start=2026-05-12T00:00:00Z&end=2026-06-11T00:00:00Z&granularity=day" -H "Authorization: Bearer $token"
curl "http://localhost:8000/api/v1/reports/pipeline-value" -H "Authorization: Bearer $token"
```

## Risks

- **Backfill missing buckets cost.** Naive Python fill is O(N) per series — fine for N=365 daily points. If month granularity over 5 years gets queried, still fine.
- **Pipeline probability misconfig.** Org with stages defaulting to 0% → forecast (Step 5) outputs zero. Defaults from pack manifest land via Phase 4.2; if a custom pipeline is created without setting probabilities, forecast outputs are documented to be "configure your pipeline probabilities" empty state.

## Rollback

`alembic downgrade -1` if the migration landed. Delete files. Revert router.
