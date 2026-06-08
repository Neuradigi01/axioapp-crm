# Step 7 — Subscription read API

**Goal:** Expose `GET /api/v1/subscriptions/current` that returns the caller's org's active subscription with all the context the billing settings page (Step 16) needs: plan code + name, status, trial days remaining, seats included vs purchased vs used, current period dates, and per-resource usage snapshot.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 1 (plan registry), Step 2 (subscription model), Step 5 (usage counters), Phase 1.6 (auth — needs `get_current_org_id`).

---

## Scope

One GET endpoint, one Pydantic response schema, one service function that composes the row + plan + usage into a single response. **Read-only.** Plan change and seat management are Steps 8 and 9.

## Endpoint

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /api/v1/subscriptions/current` | authenticated, any role | Returns the caller's org's active subscription. Visible to any role for transparency — only Owner can *change* it (Step 19 RBAC). |

### Response shape

```json
{
  "id": "uuid",
  "plan": {
    "code": "trial",
    "name": "14-day Trial",
    "monthly_bundle_usd": 0,
    "annual_bundle_usd": 0,
    "extra_seat_monthly_usd": 0,
    "extra_seat_annual_usd": 0,
    "included_seats": 3
  },
  "status": "trialing",
  "billing_cycle": "monthly",
  "trial": {
    "started_at": "2026-06-05T10:00:00Z",
    "ends_at": "2026-06-19T10:00:00Z",
    "days_remaining": 14
  },
  "period": {
    "start": "2026-06-05T10:00:00Z",
    "end": "2026-06-19T10:00:00Z",
    "renews_at": "2026-06-19T10:00:00Z"
  },
  "seats": {
    "included": 5,
    "purchased": 5,
    "in_use": 3,
    "extra_seat_cost_per_period_usd": 12
  },
  "usage": [
    {"resource": "contacts", "current": 47, "cap": 500, "is_unlimited": false},
    {"resource": "leads_per_month", "current": 12, "cap": 50, "is_unlimited": false},
    {"resource": "automation_runs_per_month", "current": 0, "cap": 0, "is_unlimited": false},
    {"resource": "form_submissions_per_month", "current": 0, "cap": 0, "is_unlimited": false},
    {"resource": "storage_mb", "current": 8, "cap": 100, "is_unlimited": false},
    {"resource": "email_sends_per_month", "current": 3, "cap": 100, "is_unlimited": false}
  ],
  "read_only": false,
  "archived": false,
  "cancelled": false,
  "stripe_customer_id": null,
  "stripe_subscription_id": null
}
```

- `trial.days_remaining` is computed: `max(0, ceil((trial_ends_at - now()) / 1 day))`. `null` if not a trial.
- `seats.in_use` is `SELECT COUNT(*) FROM tbl_organization_members WHERE org_id = ? AND is_active = true`.
- `usage` is the current value per resource from `usage_counters`. Resources not present in the table return `current: 0`.
- `read_only`, `archived`, `cancelled` are convenience booleans derived from status.

## Backend

`api/src/app/core/billing/router.py` — extend the file created in Step 1.

```python
@router.get("/subscriptions/current", response_model=SubscriptionCurrentResponse)
async def get_current_subscription(
    org_id: UUID = Depends(get_current_org_id),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionCurrentResponse:
    return await billing_service.compose_current_subscription_response(session, org_id)
```

`api/src/app/core/billing/service.py` — add:

```python
async def compose_current_subscription_response(session, org_id) -> SubscriptionCurrentResponse:
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        # Edge case: org exists but no subscription (shouldn't happen post Step 2 backfill).
        # Return a 404 with a meaningful message; frontend will treat as "needs to pick a plan."
        raise HTTPException(404, "No active subscription")
    plan = plans.get(sub.plan_code)
    seats_in_use = await user_service.count_active_members(session, org_id)
    usage_rows = await usage_service.snapshot(session, org_id, plan.caps)
    return SubscriptionCurrentResponse.from_components(sub, plan, seats_in_use, usage_rows)
```

`usage_service.snapshot` is a helper that returns a `list[UsageRow]` for each cap key in the plan, joining against `usage_counters`. Defined in Step 5; if not delivered there, add a one-line helper here.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/router.py` | modified — add `GET /subscriptions/current` |
| `api/src/app/core/billing/schemas.py` | modified — add `SubscriptionCurrentResponse`, nested `PlanShort`, `TrialInfo`, `PeriodInfo`, `SeatsInfo`, `UsageRow` |
| `api/src/app/core/billing/service.py` | modified — add `compose_current_subscription_response` |
| `api/src/app/core/billing/usage_service.py` | modified — add `snapshot(session, org_id, caps)` helper |
| `api/tests/core/billing/test_subscription_read_api.py` | created |

**5 files.** Within rule.

## Tests

`test_subscription_read_api.py`:

- **Trial org returns trial response:** auth as user in a trial org → 200, response.status = `trialing`, `trial.days_remaining` between 1 and 14, `usage` array length matches the count of cap keys for the trial plan.
- **Basic org after upgrade:** seed a Basic subscription → 200, `plan.code = 'basic'`, `plan.included_seats = 5`, `trial` field is `null`.
- **`seats.in_use` reflects real members:** add 4 active members → response shows `in_use: 4`.
- **Usage reflects metered counters:** increment `contacts` counter to 47 → response shows `usage[?(@.resource=='contacts')].current == 47`.
- **No active subscription returns 404:** delete the subscription row directly → endpoint returns 404 with "No active subscription."
- **RLS isolation:** auth as user in org A, response is for org A — no cross-org leak.
- **All roles can read:** Owner, Admin, Employee, custom roles all return 200 (read is not gated; write is gated in Step 19).
- **`read_only` flag:** set status to `read_only` → response.read_only = true; UI uses this to render the "trial ended" banner.
- **`is_unlimited` flag on usage rows:** Enterprise plan rows have `is_unlimited: true` for any resource with cap = -1.
- **`days_remaining` floors at 0:** subscription with `trial_ends_at` in the past returns 0, not negative.

## Smoke

```
docker exec template_api-api-1 pytest tests/core/billing/test_subscription_read_api.py -v

# End-to-end via curl (need JWT for a real user):
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -d 'email=ajaygogane224@gmail.com&password=...' | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/subscriptions/current | jq

# → Full SubscriptionCurrentResponse JSON.
```

Smoke against Ajay's Workspace per ops memory (`41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`).

## Risks

- **Performance: 3-4 DB hits per call** (subscription, members count, usage rows, possibly plan-config-from-yaml-but-cached). For a billing page that loads once per session, this is fine. If the trial banner (Step 15) polls the endpoint, throttle the frontend.
- **`usage_service.snapshot` reads all caps for the plan.** If a plan has 20 caps, that's 20 counter lookups. Batch into a single query: `SELECT resource, value FROM usage_counters WHERE org_id = ? AND resource = ANY(?)`. Document the query shape.
- **Stripe IDs are null during trial.** The frontend billing settings page (Step 16) must not assume they're set. If `stripe_customer_id` is null and status is anything other than `trialing`, that's a bug — but only Step 13 (webhook) populates it, so until then, expect null.

## Rollback

Revert the 5 files. Endpoint disappears; no DB or external state to roll back.
