# Step 2 — Backend: trend chart endpoint (time-series)

**Goal:** Add `GET /dashboard/trend` that returns a day-bucketed time series for a chosen metric over a chosen range. Powers the dashboard's trend chart widget. Scope (org vs personal) follows the existing dashboard rule — driven by `users.read` permission, never by role name.

## Files changed

### Modified
- `api/src/app/core/dashboard/schemas.py`
- `api/src/app/core/dashboard/service.py`
- `api/src/app/core/dashboard/router.py`

### Tests
- `api/tests/core/dashboard/test_trend_endpoint.py` (new)

## Endpoint contract

```
GET /api/v1/dashboard/trend?metric={metric}&range={range}
```

| Param | Type | Allowed | Default |
|---|---|---|---|
| `metric` | str | `leads_created`, `pipeline_value`, `calls`, `appointments` | `leads_created` |
| `range` | str | `7d`, `30d`, `90d`, `365d` | `30d` |

Response:

```python
class DashboardTrendPoint(BaseModel):
    date: date           # ISO YYYY-MM-DD, UTC bucket
    value: float         # 0.0 for missing buckets (no gaps in the series)

class DashboardTrendResponse(BaseModel):
    metric: Literal["leads_created","pipeline_value","calls","appointments"]
    range: Literal["7d","30d","90d","365d"]
    scope: Literal["org","personal"]
    points: list[DashboardTrendPoint]   # always (range_days) points, sorted ascending
```

Series always has exactly `range_days` points — missing buckets are filled with `value=0` so the chart renders smoothly with no gaps. Dates are in UTC.

## Service implementation — `service.py`

Add `assemble_trend(session, caller, metric, range_str)`:

1. Decide scope using the same `_has_users_read` helper from Step 1. Personal scope adds `assigned_to_id = caller.legacy_uuid` to every query.
2. Compute `start = now.date() - timedelta(days=range_days - 1)` so the series spans `[start, today]` inclusive.
3. Query bucket counts grouped by `func.date(<timestamp_column>)`:
   - `leads_created` → `Lead.created_at`
   - `pipeline_value` → `Lead.created_at`, summing `Lead.budget` for `status == active` rows that existed in each bucket (use a running snapshot via window function or a simpler "sum of leads created that day with budget"). **Default for v1: sum of `budget` for leads created in the bucket.** Document the simplification.
   - `calls` → `Call.started_at`
   - `appointments` → `Appointment.scheduled_at`
4. Fill missing dates: build a Python dict of `{date: value}` from the query rows, then iterate `start..today` filling zeros for absent keys.
5. Tenant filter on every query: `WHERE org_id = :caller.org_id` (RLS still enforced; explicit filter for safety).

Tightening rules:
- All four metrics use the same outer shape so the frontend can swap metric without conditional rendering.
- Bucket boundaries are date-only (no hour buckets) — keeps the series human-readable and avoids timezone surprises across DST.
- Range max is 365d to bound query cost; reject longer with 422 (FastAPI `Literal` handles this).

## Router — `router.py`

```python
@router.get("/trend", response_model=DashboardTrendResponse)
async def dashboard_trend(
    metric: Literal["leads_created","pipeline_value","calls","appointments"] = "leads_created",
    range: str = Query("30d", regex="^(7d|30d|90d|365d)$"),
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardTrendResponse:
    return await assemble_trend(session, caller, metric, range)
```

No new permission key. The endpoint is callable by anyone who can hit `/dashboard/summary` today.

## Tests — `test_trend_endpoint.py`

Three scenarios:

1. **Series length and zero-fill.** Seed three leads across two non-adjacent days in the last 7d. Call `GET /dashboard/trend?metric=leads_created&range=7d` → assert `len(points) == 7`, the two seeded days have nonzero values, the other five are `0`.
2. **Scope split.** Two users in one org: one with `users.read`, one without. Each seeds five leads, but assigned only to their own user. Call as each → org-scope sees all 10 in the series; personal-scope sees only their own 5.
3. **Bad range / metric → 422.** Hit `?range=99d` and `?metric=banana` → assert 422 with FastAPI's standard validation error shape.

## Verification checklist

**Backend:**
- `curl '/api/v1/dashboard/trend?metric=leads_created&range=30d'` (org-scope user) → 200, `points` has 30 entries with ISO dates ascending.
- `curl '/api/v1/dashboard/trend?metric=pipeline_value&range=90d'` → 200, values are sums of `Lead.budget` per bucket.
- Switch caller to personal-scope user → response `scope == "personal"`, values restricted to that user.
- pytest green: `uv run pytest tests/core/dashboard/test_trend_endpoint.py -v`.

**Frontend:** No frontend change in this step.

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 2: explicit `org_id` filter on every query.
- [ ] Rule 6: no new permission keys.
- [ ] Rule 8: 3 files modified + 1 test file, ≤250 LOC.
- [ ] Rule 10: zero-fill behaviour is explicit (no missing days); range/metric are whitelisted (no SQL injection surface).

## Stop & report

Awaiting "proceed" before Step 3.
