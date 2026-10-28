# Step 3 — Backend: pipeline funnel endpoint

**Goal:** Add `GET /dashboard/funnel` that returns lead counts per pipeline stage over a chosen range. Powers the dashboard's funnel chart widget. Scope follows the existing dashboard rule.

## Files changed

### Modified
- `api/src/app/core/dashboard/schemas.py`
- `api/src/app/core/dashboard/service.py`
- `api/src/app/core/dashboard/router.py`

### Tests
- `api/tests/core/dashboard/test_funnel_endpoint.py` (new)

## Endpoint contract

```
GET /api/v1/dashboard/funnel?range={range}
```

| Param | Type | Allowed | Default |
|---|---|---|---|
| `range` | str | `7d`, `30d`, `90d`, `365d` | `30d` |

Response:

```python
class FunnelStageBucket(BaseModel):
    stage_id: uuid.UUID
    stage_name: str
    stage_order: int      # for stable left-to-right rendering
    count: int

class DashboardFunnelResponse(BaseModel):
    range: Literal["7d","30d","90d","365d"]
    scope: Literal["org","personal"]
    total_leads_in_range: int                      # convenience for the "% of total" labels
    stages: list[FunnelStageBucket]                # always includes every active stage, even when count == 0
    won_count: int                                 # closed-won in range
    lost_count: int                                # closed-lost in range
```

The stages list always contains every active pipeline stage (in `stage_order` ascending) so the chart's bar count is deterministic and zero-stages render as empty bars rather than missing entries. `won_count` / `lost_count` are returned separately because they correspond to terminal lead statuses (`won` / `lost`), not stages.

## Service implementation — `service.py`

Add `assemble_funnel(session, caller, range_str)`:

1. Decide scope using `_has_users_read`. Personal scope adds `assigned_to_id = caller.legacy_uuid`.
2. Compute `start = now - timedelta(days=range_days)`.
3. Fetch all active pipeline stages for the caller's org (`Stage.is_active == True`), ordered by `stage_order`. **Use the existing pipelines models — do not duplicate stage data.**
4. Group `Lead` rows by `stage_id` for leads with `created_at >= start AND org_id = caller.org_id` (and the personal-scope filter when applicable). Use a `LEFT JOIN` on stages so empty stages still appear with `count = 0`.
5. Won / lost counts: a separate aggregate over the same range filter, grouped by `Lead.status`.
6. `total_leads_in_range` = sum of all stage counts plus won + lost.

Tightening rules:
- Stages from other orgs cannot leak — query stages with `Stage.org_id == caller.org_id`.
- A stage that has been soft-deleted (`is_active == False`) is excluded from the response even if historical leads point to it; that's correct funnel behaviour (we don't want phantom columns for retired stages).
- Stage join on `Lead.stage_id` is `LEFT` to preserve the every-stage guarantee.

## Router — `router.py`

```python
@router.get("/funnel", response_model=DashboardFunnelResponse)
async def dashboard_funnel(
    range: str = Query("30d", regex="^(7d|30d|90d|365d)$"),
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardFunnelResponse:
    return await assemble_funnel(session, caller, range)
```

No new permission key.

## Tests — `test_funnel_endpoint.py`

Three scenarios:

1. **Every stage present.** Seed an org with 4 stages and 3 leads (one in stages 0 and 2, none in stages 1 and 3). Call `GET /dashboard/funnel?range=30d` → assert 4 entries returned in `stages`, counts `[1, 0, 1, 0]`, `stage_order` ascending.
2. **Scope split.** Two users; org-scope sees both their leads, personal-scope sees only own. Won/lost counts respect scope.
3. **Out-of-range leads excluded.** Lead created 120 days ago + `range=30d` → not counted. Same lead + `range=365d` → counted.

## Verification checklist

**Backend:**
- `curl '/api/v1/dashboard/funnel?range=30d'` (org-scope user) → 200, stages list includes every active pipeline stage with counts.
- Won / lost counts match a manual SQL query of `Lead.status IN ('won','lost')` over the same range.
- Switch caller to personal-scope → `scope == "personal"`, counts restricted.
- pytest green: `uv run pytest tests/core/dashboard/test_funnel_endpoint.py -v`.

**Frontend:** No frontend change in this step.

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 2: `org_id` filter on every query (stages and leads both).
- [ ] Rule 6: no new permission keys.
- [ ] Rule 8: 3 files modified + 1 test file, ≤220 LOC.
- [ ] Rule 10: deterministic stage ordering; no implicit ordering by id.

## Stop & report

Awaiting "proceed" before Step 4.
