# Step 2 — Backend: conversion funnel endpoint (walk-in → lead → quoted → won)

**Goal:** Single endpoint returning a 4-stage funnel: Walk-ins → Leads → Quoted → Won, with counts + conversion % between stages + per-stage drilldown row IDs.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Step 1 (foundation), Phase 2 (contacts, leads, walk-ins, pipelines).

---

## Scope

In-scope:

- `core/reporting/queries/funnel.py`:
  - `compute_funnel(session, org_id, actor_id, date_range, scope)` → returns `FunnelResponse`:
    ```python
    {
      "stages": [
        {"key": "walk_in", "label": "Walk-ins",  "count": 1042, "conversion_pct": null},
        {"key": "lead",    "label": "Leads",     "count": 387,  "conversion_pct": 37.1},
        {"key": "quoted",  "label": "Quoted",    "count": 124,  "conversion_pct": 32.0},
        {"key": "won",     "label": "Won",       "count": 43,   "conversion_pct": 34.7},
      ],
      "totals": {"start": 1042, "end": 43, "overall_pct": 4.1},
      "drilldown_url_template": "/api/v1/reports/funnel/{stage_key}/contacts?start=...&end=..."
    }
    ```
- Drilldown endpoint `GET /reports/funnel/{stage_key}/contacts` — returns contact IDs at that stage during the date range (paginated, capped 1000).
- Funnel stage mapping is read from the pipeline configuration so a furniture pack with custom stages still funnels correctly:
  - `walk_in`: count of `walk_ins` created in range.
  - `lead`: count of `leads` created in range (any stage).
  - `quoted`: count of `leads` whose pipeline stage transitioned to a stage with `is_quote_stage=true` in range. (Pipelines schema already has stage metadata.)
  - `won`: count of `leads` with `status='won'` in range.
- Date-range semantics: count by `created_at` (walk_ins, leads) / `stage_changed_at` (quoted) / `won_at` (won). Document on the endpoint.
- Cached (60s TTL per Step 1).
- Permission gate `reports.read`; scope respected (own → only actor's records).

Out of scope:

- Custom-funnel-stage editor — v2.
- Per-source funnel splits (Google Ads funnel vs Meta Ads funnel) — Step 4's revenue split covers source; a future flag can extend funnel.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/reporting/queries/__init__.py` | created |
| `api/src/app/core/reporting/queries/funnel.py` | created |
| `api/src/app/core/reporting/router.py` | modified — add `/funnel` + `/funnel/{stage}/contacts` |
| `api/tests/test_reporting_funnel.py` | created |

**4 files.**

## Plan

1. `funnel.py` query: a single SQL with four `WITH` CTEs counting per stage, joined to produce conversion %. Or four parallel queries via `asyncio.gather` if a single query gets unwieldy — pick simpler.
2. Drilldown query: per `stage_key`, return the matching contact IDs. Paginate.
3. Router wires both into `/reports/funnel*`. Both decorated with `@cached(ttl_seconds=60)` from Step 1.

## Tests

`api/tests/test_reporting_funnel.py`:

- **Seeded fixtures:** seed 100 walk-ins, 40 leads (35 from walk-ins via link), 15 quoted, 6 won.
- **Counts correct:** funnel returns 100, 40, 15, 6.
- **Conversion % correct:** lead→quoted 37.5%, quoted→won 40%.
- **Overall pct:** 6/100 = 6%.
- **Empty range:** range with no data → all zeros, conversion % null.
- **Date filter respected:** walk-in 60 days ago not counted when range is 30 days.
- **Scope=own:** Sales Executive sees only their assigned records.
- **RLS:** Org B's funnel does not include Org A's data.
- **Drilldown:** GET drilldown for `lead` stage returns the 40 lead IDs.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_funnel.py -v

$token = "<owner JWT>"
curl "http://localhost:8000/api/v1/reports/funnel?start=2026-05-12T00:00:00Z&end=2026-06-11T00:00:00Z" `
  -H "Authorization: Bearer $token"
```

## Risks

- **Stage definition drift.** If a pack rewrites pipeline stages and forgets `is_quote_stage`, the "Quoted" count goes to 0. Mitigation: log a warning when no quote-marked stage exists for the org; UI surfaces "configure your quote stage" empty-state.
- **Walk-in → lead linkage.** Walk-ins that don't convert to leads are still counted at the walk-in stage but never propagate downstream — that's the point of a funnel. Document on the endpoint that the 4 counts are NOT a strict subset chain (they're per-stage event counts), they just imply conversion when read top-to-bottom. UI explains via tooltip.

## Rollback

Delete files. Revert router. Funnel endpoint disappears; widgets that consume it 404 until rolled forward again.
