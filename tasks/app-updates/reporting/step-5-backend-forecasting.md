# Step 5 — Backend: forecasting endpoint (pipeline × stage probability)

**Goal:** Projected close revenue for the next 3 months, computed as Σ (lead.value × stage.probability_pct) per expected-close-month, with a confidence band derived from past 90 days' actual-vs-predicted variance.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Step 1 (foundation), Step 4 (pipeline-value query — reuses joins).

---

## Scope

In-scope:

- `core/reporting/queries/forecast.py`:
  - `forecast(session, org_id, months_ahead=3)` → list of `ForecastBucket`:
    ```python
    {
      "month": "2026-07",
      "projected_inr": 580000,
      "low_inr": 460000,           # projected × (1 - variance)
      "high_inr": 700000,          # projected × (1 + variance)
      "lead_count": 18,
      "by_stage": [
        {"stage_key": "quoted", "weighted_inr": 320000, "lead_count": 8},
        {"stage_key": "negotiation", "weighted_inr": 260000, "lead_count": 10},
      ]
    }
    ```
- Expected-close-month: each lead has `expected_close_at`. If null, lead is excluded from forecast (documented). UI surfaces "N leads have no expected close date — they aren't in the forecast" prompt so Owner knows to set them.
- Variance: compute past 90d sum of (won_value) / sum(forecast_at_t-30) where t is each day's then-current 30-day forecast. Hard to back-derive from current schema — fall back to a simpler proxy: `variance = stddev(won_value over past 12 weekly buckets) / mean(won_value over past 12 weekly buckets)`. Clamp to [0.1, 0.6] so the band is always meaningful and never absurd.
- Endpoint `GET /reports/forecast?months_ahead=3`.
- Cached (TTL 120s — forecast doesn't move minute to minute).

Out of scope:

- ML-driven forecasting — explicit non-goal for v1; this is the "industry standard pipeline × probability" approach.
- Per-rep forecast — possible follow-on by passing `scope=own`; not budgeted here.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/reporting/queries/forecast.py` | created |
| `api/src/app/core/reporting/router.py` | modified — add `/forecast` |
| `api/tests/test_reporting_forecast.py` | created |

**3 files.**

## Plan

1. Pull all open leads (`status='active'`) with non-null `expected_close_at` falling within the next N months.
2. Group by `to_char(expected_close_at, 'YYYY-MM')` and `pipeline_stage_id`.
3. Per group: `weighted_inr = sum(value * stage.probability_pct / 100)`.
4. Variance subquery: weekly sum of `value` for won leads over past 12 weeks → stddev / mean. Clamp.
5. Apply variance to per-month projected → low + high bands.

## Tests

`api/tests/test_reporting_forecast.py`:

- **Single-stage forecast:** 4 leads all in "quoted" (prob 50%), value 100K each, close in July 2026 → projected 200K (50% of 400K).
- **Multi-stage aggregation:** mix of stages, verify weighted sum.
- **No expected_close_at excludes:** seed a lead without date → not in any bucket; response includes `leads_without_close_date: N`.
- **Variance band:** with 12 weeks of seeded won data → variance computed; low + high present and ordered (`low <= projected <= high`).
- **Variance clamp:** with 0 historical data → variance = 0.1 floor.
- **Months_ahead respected:** months_ahead=1 → 1 bucket; months_ahead=6 → 6 buckets.
- **RLS isolation.**

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_forecast.py -v

curl "http://localhost:8000/api/v1/reports/forecast?months_ahead=3" -H "Authorization: Bearer $token"
```

## Risks

- **Wrong-shaped data → silly numbers.** Org with no won history → variance falls back to floor (0.1) so band is ±10% — fine. Org with one massive outlier won → variance spikes → band gets wide. Acceptable; honest.
- **Stage probability misconfig.** Already flagged in Step 4 — if probabilities are all 0, projected is 0. UI shows "configure stage probabilities" empty state.
- **`expected_close_at` data hygiene.** Most Owners won't set this consistently on every lead. The "N leads without close date" counter in the response gives the Reports page a nudge to backfill. Document.

## Rollback

Delete files. Revert router.
