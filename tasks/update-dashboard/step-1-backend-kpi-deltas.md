# Step 1 — Backend: period-over-period deltas on KPI cards

**Goal:** Extend every numeric KPI card in `/dashboard/summary` to carry a prior-period value, percentage delta, and trend direction so the frontend can render `↑ 12%` / `↓ 4%` / `→` arrows. Keep the existing card payload backward-compatible — `value` stays where it is; the delta fields are additive.

## Files changed

### Modified
- `api/src/app/core/dashboard/schemas.py`
- `api/src/app/core/dashboard/service.py`
- `api/src/app/core/dashboard/router.py` (no signature change; only revalidate)

### Tests
- `api/tests/core/dashboard/test_kpi_deltas.py` (new)

## Schema changes — `schemas.py`

Extend `DashboardCard` with three optional fields:

```python
previous_value: float | int | None = None
delta_pct: float | None = None       # signed percentage, e.g. +12.3 or -4.0
delta_direction: Literal["up", "down", "flat"] | None = None
```

All three are `None` for `format == "leaderboard"` and `format == "text"` cards (no comparison makes sense). For `format in {"number", "currency", "percent"}` they are always populated.

## Service changes — `service.py`

Add a small helper:

```python
def _delta(current: float, previous: float) -> tuple[float, Literal["up","down","flat"]]:
    """Return (signed_percent, direction). previous==0 collapses to +100 if current>0, else flat."""
```

Rules:
- `previous == 0` and `current > 0` → `(100.0, "up")`
- `previous == 0` and `current == 0` → `(0.0, "flat")`
- otherwise → `round((current - previous) / previous * 100, 1)`
- direction = `"up"` if delta > 0.05, `"down"` if delta < -0.05, else `"flat"` (avoids noisy near-zero arrows).

Per-card prior-period rule (keep each card's existing semantic; the prior period mirrors it):

| Card | Current window | Prior window |
|---|---|---|
| `leads.new_today` / `leads.my_today_*` | today | yesterday |
| `appointments.today` / `appointments.my_today` | today | yesterday |
| `tasks.open_count` / `tasks.my_open` | as-of now | as-of 7 days ago (snapshot via `created_at <= now-7d AND (closed_at IS NULL OR closed_at > now-7d)`) |
| `calls.this_week` / `calls.my_this_week` | week-to-date | same offset in the previous week |
| `leads.pipeline_value` | active leads now | active leads as-of 30 days ago |
| `contacts.total` | total now | total 30 days ago |
| `conversion.rate` / `conversion.my_rate` | last 30d | the 30d before that |
| `top_performers` | this week | (no delta — leaderboard) |

Implement each prior-period query alongside its current-period query in `_assemble_org_cards` / `_assemble_personal_cards`. Use the existing SQLAlchemy `select` pattern; no raw SQL.

For the "as-of 30 days ago" snapshots, filter the existing tables by `created_at < now-30d` for cumulative counters (contacts) and by `(status, updated_at)` for state-dependent ones (active leads pipeline). Document the assumption inline.

After each pair of values is computed, build the card with `_delta(...)` populated. Leaderboard cards skip delta fields.

## Router changes — `router.py`

No new endpoint, no new query params. The existing `GET /dashboard/summary` payload gains the three new fields per card. FastAPI re-validates against the updated `DashboardCard` schema automatically — bump the response model only if it's imported elsewhere.

## Tests — `test_kpi_deltas.py`

Three small scenarios, each in its own org via the standard test harness:

1. **Org scope, with growth.** Seed leads such that today has 5, yesterday had 4 → assert `leads.new_today` card returns `value=5, previous_value=4, delta_pct=25.0, delta_direction="up"`.
2. **Personal scope, no change.** Seed one user's leads such that today's count equals yesterday's → assert `delta_direction="flat"` and `delta_pct` near 0.
3. **Zero-baseline case.** Previous period zero, current > 0 → assert `delta_pct=100.0, delta_direction="up"` (no division-by-zero).

Tests assert against the JSON shape of `/dashboard/summary`, not the service layer directly, so a regression in either the schema or the assembly path is caught.

## Verification checklist

**Backend:**
- `curl /api/v1/dashboard/summary` (org-scope user) → every `number` / `currency` / `percent` card has `previous_value`, `delta_pct`, `delta_direction` populated.
- Leaderboard card (`top_performers`) returns `null` for the three delta fields.
- Switch caller to a personal-scope user → personal cards likewise carry deltas.
- All `delta_direction` values fall in `{"up","down","flat"}`; no exceptions on a freshly-seeded org.
- pytest green: `uv run pytest tests/core/dashboard/test_kpi_deltas.py -v`.

**Frontend:** No frontend change in this step. The current template ignores unknown fields, so the existing dashboard continues to render unchanged.

## Self-check (10 rules)

- [ ] Rule 1: no imports from `packs/`.
- [ ] Rule 2: every new query filters by `org_id`.
- [ ] Rule 6: no new permission keys.
- [ ] Rule 8: ≤5 files touched, ≤200 LOC.
- [ ] Rule 10: no TODOs; every card returns either fully-populated deltas or explicit `null`s — no half-states.

## Stop & report

Awaiting "proceed" before Step 2.
