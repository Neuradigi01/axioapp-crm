# Step 1 — Backend: reporting foundation (date-range, query base, RLS, Redis cache)

**Goal:** Land `core/reporting/` and the shared primitives every reporting endpoint will use: a `DateRange` schema, a parameterised SQL helper that always honours RLS, a Redis cache wrapper keyed per (org, role-scope, query-hash), and the router skeleton.
**Track:** App Updates → Reporting
**Status:** Pending
**Depends on:** Phase 1.5 (permissions, audit), Redis (locked stack).

---

## Scope

In-scope:

- `core/reporting/` sub-package:
  - `schemas.py` — `DateRange`, `Granularity` enum (day/week/month), `RolesScope` enum (own/team/org), `MetricPoint`, `TimeSeriesResponse`, `FunnelStageResponse`, `LeaderboardRow`, `KPITile`.
  - `service.py` — `run_query(sql, binds, org_id) -> list[dict]`. Always sets `app.org_id` and `app.actor_id` via `SET LOCAL` inside the transaction so RLS + per-user scoping work consistently.
  - `cache.py` — `cached(key_parts, ttl) -> decorator`. Serialises (org_id, role-scope-hash, query-hash, date-range) into a stable key; uses `redis.asyncio` from the existing pool.
  - `router.py` — empty router mounted at `/api/v1/reports/`; specific endpoints added in Steps 2–5.
  - `module.py` — descriptor with `frontend_route='/user/reports'`, permission `reports.read`.
- Permission keys: `reports.read`, `reports.export`. Defaults: Owner + Store Manager + Senior Sales Executive have both. Sales Executive has `reports.read` scoped to own.
- Role-scope resolver: `scope_for(actor) -> RolesScope` returning `org | team | own` based on the actor's role. Each query endpoint uses this to drive its filter (`WHERE owner_id = $actor` for `own`, etc.).
- Date-range query-param helper: parses `?start=ISO&end=ISO` with bounds (max 365 days), returns `DateRange`. Defaults to last 30 days when omitted.
- Audit events: `reports.viewed.{report_name}` emitted once per report load (not per cache hit) for usage analytics.

Out of scope:

- The actual query implementations (Steps 2–5).
- The widget library (Step 6).
- Reports page (Step 7).
- Scheduled reports (Step 8).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/reporting/__init__.py` | created |
| `api/src/app/core/reporting/schemas.py` | created |
| `api/src/app/core/reporting/service.py` | created |
| `api/src/app/core/reporting/cache.py` | created |
| `api/src/app/core/reporting/router.py` | created |
| `api/src/app/core/reporting/module.py` | created |
| `api/src/app/core/permissions/registry.py` | modified — register `reports.read`, `reports.export` |
| `api/src/app/main.py` | modified — include router |
| `api/tests/test_reporting_foundation.py` | created |

**9 files.**

## Plan

1. `schemas.py`: standard Pydantic v2 models. `DateRange` has `start: datetime`, `end: datetime`, validator that rejects `start > end` and ranges > 365 days.
2. `service.run_query`:
   ```python
   async def run_query(session, sql, binds, org_id, actor_id):
       await session.execute(text("SET LOCAL app.org_id = :o"), {"o": str(org_id)})
       await session.execute(text("SET LOCAL app.actor_id = :a"), {"a": str(actor_id)})
       result = await session.execute(text(sql), binds)
       return [dict(row._mapping) for row in result]
   ```
   Every reporting query uses this — guarantees RLS context is set even when SQLAlchemy ORM isn't involved.
3. `cache.cached`:
   ```python
   def cached(ttl_seconds=60):
       def decorator(fn):
           async def wrapper(*args, **kwargs):
               key = _key_from(fn.__qualname__, kwargs)  # excludes session, includes org_id + scope + binds
               cached_value = await redis.get(key)
               if cached_value:
                   return json.loads(cached_value)
               result = await fn(*args, **kwargs)
               await redis.setex(key, ttl_seconds, json.dumps(result, default=str))
               return result
           return wrapper
       return decorator
   ```
4. Permission registration.
5. Router skeleton: `GET /reports/ping` returning `{"ok": true, "date_range": …}` to verify the date-range helper works. Used by tests + smoke.
6. Audit emit helper: `emit_view(report_name, actor)` — only fires on cache miss (real query); not on cache hit.

## Tests

`api/tests/test_reporting_foundation.py`:

- **DateRange validation:** start > end → 422; range > 365d → 422; missing both → defaults to last 30d.
- **run_query sets RLS:** seed two orgs; run a SELECT against a tenant-scoped table from Org A's context → only Org A's rows returned.
- **Cache hit/miss:** first call hits DB (assertion via mock counter); second call within TTL hits cache; cache expires after TTL → next call hits DB again.
- **Cache key isolation per org:** Org A's cached query does not leak to Org B's call.
- **Cache key isolation per scope:** Owner's `own` scope vs Sales Executive's `own` scope key differently.
- **Permission gate:** rep without `reports.read` → 403 on /reports/ping.
- **Audit emit-once:** call ping twice in a row (second is cache hit) → only one `reports.viewed.ping` audit row.

## Smoke

```powershell
docker exec template_api-api-1 uv run pytest tests/test_reporting_foundation.py -v

$token = "<owner JWT>"
curl "http://localhost:8000/api/v1/reports/ping?start=2026-05-12T00:00:00Z&end=2026-06-11T00:00:00Z" `
  -H "Authorization: Bearer $token"
# Expect: { "ok": true, "date_range": { "start": "...", "end": "..." }, "days": 30 }
```

## Risks

- **RLS bypass via raw SQL.** If a future query uses string-interpolation instead of binds, it could bypass `app.org_id`. Mitigation: code review + a CI grep for `f"…{` in `core/reporting/queries/*.py`.
- **Cache memory growth.** 60s TTL caps growth at ~60s × peak QPS × payload-size. At reasonable scale (1K orgs, 10 reports each, 10KB payload, 60s TTL) → ~6MB steady-state. Acceptable.
- **Stale-cache UX surprise.** Users see a metric, fix data in CRM, refresh → still see old number until cache expires. Mitigation: surface a "Last updated XXs ago" badge on every widget (Step 6) so the staleness is visible.
- **`SET LOCAL` interaction with connection pooling.** SQLAlchemy releases the connection at transaction end; the `LOCAL` setting dies with the transaction. Correct behaviour. Verified by test 2.

## Rollback

Delete files. Revert permissions + main.py edits. The downstream Steps 2–5 cannot land without this foundation; rolling back this implies rolling back everything.
