# Step 5 — Usage metering

**Goal:** A `usage_counters` table + service that tracks current consumption of capped resources (contacts, leads, automation runs, API calls, form submissions, etc.) per org per billing period — so cap enforcement reads a denormalized counter instead of running `SELECT COUNT(*)` on hot paths.
**Track:** Pricing and Billing
**Status:** Pending
**Depends on:** Step 2 (subscription model — needs `current_period_start/end` to know which window to bucket counters into).

---

## Scope

One new table, one Alembic migration, two service functions (`increment`, `get`), and a periodic Celery task that resets monthly counters at period rollover. Call sites that need to enforce caps will plug into `usage_service.get_for(org_id, resource)` in their `current_provider` (Step 4) and `usage_service.increment(...)` in their write path. **This step does not retrofit existing endpoints** — that's incremental work as Phase 5 lands.

## Schema

### New table: `usage_counters`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK → `organizations.id` | indexed; RLS scope |
| `resource` | TEXT NOT NULL | e.g. `contacts`, `leads_per_month`, `automation_runs_per_month` |
| `period_kind` | TEXT NOT NULL | `lifetime` (e.g. contacts — counted forever) or `monthly` (e.g. automation runs — resets each billing cycle) |
| `period_start` | TIMESTAMPTZ NOT NULL | for `monthly`, equals `subscription.current_period_start`; for `lifetime`, equals subscription creation date |
| `period_end` | TIMESTAMPTZ NOT NULL | for `monthly`, equals `subscription.current_period_end`; for `lifetime`, far future sentinel (`9999-12-31`) |
| `value` | BIGINT NOT NULL DEFAULT 0 | the count |
| `updated_at` | TIMESTAMPTZ NOT NULL | |

### Indexes

| Index | Purpose |
|---|---|
| `usage_counters_org_resource_idx` (UNIQUE) on `(org_id, resource, period_start)` | one counter per org+resource+period |
| `usage_counters_org_resource_lookup_idx` on `(org_id, resource)` | fast read |
| RLS policy `usage_counters_org_isolation` | per Rule 2 |

### Counter taxonomy

| Resource | period_kind | Notes |
|---|---|---|
| `contacts` | `lifetime` | cumulative; deletes decrement |
| `leads_per_month` | `monthly` | only counts new leads created in period |
| `storage_mb` | `lifetime` | cumulative; file deletes decrement |
| `form_submissions_per_month` | `monthly` | resets at period rollover |
| `automation_runs_per_month` | `monthly` | resets at period rollover |
| `api_calls_per_day` | `monthly` | _Note: this one is special — resets daily, not monthly_ |
| `email_sends_per_month` | `monthly` | |
| `sms_sends_per_month` | `monthly` | |

The `period_kind` enum should support: `lifetime`, `monthly`, `daily`. Daily counters use `period_start = today_midnight`, `period_end = tomorrow_midnight`.

## Backend

### Service: `usage_service.py`

```python
async def increment(session, org_id: UUID, resource: str, delta: int = 1) -> int:
    """
    Atomically increment the current-period counter for (org_id, resource). Creates
    the row if it does not exist. Returns the new value.

    Uses Postgres ON CONFLICT to be race-safe.
    """

async def get(session, org_id: UUID, resource: str) -> int:
    """Read current-period counter. Returns 0 if no row exists."""

async def reset_monthly_counters(session, org_id: UUID) -> None:
    """
    Called by the period-rollover Celery task. Inserts a new row for each
    'monthly' resource with value=0 and the new period_start/end.
    """
```

### Atomic increment via ON CONFLICT

```sql
INSERT INTO usage_counters (org_id, resource, period_kind, period_start, period_end, value, updated_at)
VALUES (:org_id, :resource, :period_kind, :period_start, :period_end, :delta, now())
ON CONFLICT (org_id, resource, period_start)
DO UPDATE SET value = usage_counters.value + EXCLUDED.value, updated_at = now()
RETURNING value;
```

The `(org_id, resource, period_start)` unique index ensures one row per period.

### Period rollover task

`api/src/app/core/billing/tasks.py`:

```python
@celery_app.task
def rollover_period_counters():
    """
    Runs hourly (Celery Beat). For each org whose subscription.current_period_end has passed:
      - update subscription.current_period_start = old end, current_period_end = old end + 1 month (or year)
      - reset monthly counters for that org

    This task runs once per period boundary; if missed, catches up.
    """
```

Daily counters (`api_calls_per_day`) reset via a separate `reset_daily_counters` task that runs at midnight UTC.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_usage_counters_table.py` | created |
| `api/src/app/core/billing/models.py` | modified — add `UsageCounter` model |
| `api/src/app/core/billing/usage_service.py` | created — `increment`, `get`, `reset_monthly_counters` |
| `api/src/app/core/billing/tasks.py` | created — Celery rollover tasks |
| `api/src/app/shared/celery_app.py` (or equivalent) | modified — register beat schedule for the two reset tasks |
| `api/tests/core/billing/test_usage_metering.py` | created |

**6 files + 1 migration.** Within rule.

## Tests

`test_usage_metering.py`:

- **`increment` creates row on first call:** before, no row; after, `value=1`. Idempotent on subsequent calls — values stack.
- **Race-safe increment:** spawn 50 concurrent increments → final value is exactly 50 (proves the ON CONFLICT path).
- **`get` returns 0 for unknown resource:** no row, returns 0.
- **Cross-org isolation:** org A's counter is not visible to org B (RLS check).
- **`reset_monthly_counters` zeros monthly resources but leaves lifetime alone:** insert a `contacts` (lifetime) row with value=100 and an `automation_runs_per_month` (monthly) row with value=50; call reset; contacts stays 100, automation gets a new row with value=0 for the new period.
- **Rollover task advances `current_period_start/end` on subscription:** force `current_period_end = now() - 1 hour`, run task, assert subscription period advances and counters reset.
- **Daily counter resets at midnight:** force `period_end < now()` on a daily counter, run `reset_daily_counters`, assert new period row created.

## Smoke

```
.\API\docker-helper.cmd migrate
docker exec template_api-api-1 pytest tests/core/billing/test_usage_metering.py -v

# Manual increment from a Python shell:
docker exec -it template_api-api-1 uv run python -c "
import asyncio
from app.core.billing import usage_service
from app.shared.db import async_session
from uuid import UUID
async def go():
    async with async_session() as s:
        v = await usage_service.increment(s, UUID('41f9ede9-41b3-44ce-b489-3004566d4068'), 'contacts')
        print('Contacts counter:', v)
asyncio.run(go())
"
# → prints '1' on first run, '2' on second, etc.

# Force rollover:
docker exec template_api-api-1 celery -A app.shared.celery_app call app.core.billing.tasks.rollover_period_counters
```

## Risks

- **Counters drift from reality if a delete handler forgets to decrement.** Mitigation: every entity that contributes to a `lifetime` counter (contacts, files) must wrap its create + delete in `usage_service.increment(delta=+1 / -1)`. Add a CI lint rule or a periodic reconciliation task in a follow-up step if drift is observed.
- **Period rollover can miss if Celery beat is down.** Catch-up logic in the task: if `current_period_end` is in the past by more than one period, advance multiple periods. Document the edge case.
- **Daily counter has high write volume.** For an org doing 100k API calls/day on Standard, that's 100k increments. Postgres can handle this but watch the row update latency. Consider batched increments (in-memory bucket flushed every N seconds) as a follow-up if needed — out of scope for v1.
- **The `current_period_start` referenced in `(org_id, resource, period_start)` unique index** is the *subscription's* period for monthly counters, not the day. If the period boundary moves (e.g. Stripe-side period changes on plan upgrade), the `period_start` value changes, which is a NEW row, not an update. That's correct — but consumers reading "current" must filter by `period_start <= now() < period_end`, not by `period_start = subscription.current_period_start` (race during transition).

## Rollback

Revert the 6 source files + downgrade the migration. The `usage_counters` table drops cleanly. Celery beat schedule reverts with the file. Any cap enforcement that started using counters falls back to "always allow" if rolled back — verify Step 4 decorators tolerate a None response from the counter provider.
