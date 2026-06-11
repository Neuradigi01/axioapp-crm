# Step 3 — Backend: sales-by-rep + leaderboard endpoint with targets

**Goal:** Per-rep performance table: leads handled, conversations replied to, won count, won value (INR), target attainment %, period-over-period trend.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Step 1 (foundation), Phase 3.6 (staff targets).

---

## Scope

In-scope:

- `core/reporting/queries/sales_by_rep.py`:
  - `leaderboard(session, org_id, date_range, scope)` → `list[LeaderboardRow]`:
    ```python
    {
      "user_id": "...",
      "name": "Asha Patel",
      "role": "sales_executive",
      "leads_handled": 87,
      "conversations_replied": 142,
      "won_count": 9,
      "won_value_inr": 412000,
      "target_value_inr": 500000,
      "target_attainment_pct": 82.4,
      "trend_pct_vs_prior": 12.3
    }
    ```
- Endpoint `GET /reports/sales-by-rep?start=&end=&scope=team|org`:
  - Owner / Store Manager: defaults `scope=org`; can switch to `scope=team` (their team only).
  - Sales Executive: forced to single-row of self (uses Step 1's scope resolver).
- Trend: same window length shifted backward by `(end - start)` → compute won_value delta %.
- Targets: read from `staff_targets` table (Phase 3.6) keyed on (user_id, period). If no target set, attainment shows null.
- Cached.

Out of scope:

- Activity-source attribution (which channel drove the won) — Step 4 splits revenue by source.
- Per-product / per-category leaderboard — v2.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/reporting/queries/sales_by_rep.py` | created |
| `api/src/app/core/reporting/router.py` | modified — add `/sales-by-rep` |
| `api/tests/test_reporting_sales_by_rep.py` | created |

**3 files.**

## Plan

1. SQL with `users` LEFT JOIN aggregates from `leads` (count, won_count, sum(value) where status='won') + `messages` (count direction='outbound') + `staff_targets` (target value for the period).
2. Trend query: same aggregate over prior window. Two queries + Python dict merge is simpler than one big CTE; reach for the CTE only if perf demands.
3. Sort: default by `won_value_inr DESC`; allow `?sort=name|attainment_pct|trend`.

## Tests

`api/tests/test_reporting_sales_by_rep.py`:

- **Seeded:** 3 reps with varying lead counts + 2 with set targets.
- **Counts + sums correct:** verify per-row aggregates.
- **Target attainment:** rep with target 500K + won 412K → 82.4%.
- **No target → null attainment:** rep without a `staff_targets` row → `target_attainment_pct=null`.
- **Trend calculation:** seed prior-window data; verify delta %.
- **Scope=own:** Sales Executive sees only self.
- **Sort order:** default desc by won_value; passing sort=name reorders.
- **RLS:** Org B's reps not in Org A's leaderboard.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_sales_by_rep.py -v

curl "http://localhost:8000/api/v1/reports/sales-by-rep?start=2026-05-12T00:00:00Z&end=2026-06-11T00:00:00Z" `
  -H "Authorization: Bearer $token"
```

## Risks

- **Trend explosion for new reps.** Rep with 0 prior, X current → infinity %. Cap displayed trend at +999% or show "new"; return `None` in payload when prior is 0; frontend displays "new" badge instead of a number.
- **Won-value currency.** Defaults to INR per pack manifest. If multi-currency lands later, this query needs a per-row currency column. Not blocking for v1.

## Rollback

Delete files. Revert router. Endpoint disappears.
