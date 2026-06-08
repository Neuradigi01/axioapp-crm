# Step 8 — Plan change API

**Goal:** `POST /api/v1/subscriptions/change` — the server-side state transition for a plan change (upgrade, downgrade, or billing-cycle switch). **Does not handle payment yet** — that's Steps 11–13. This endpoint computes the intended new state and either applies it directly (when no charge required, e.g. downgrade-at-renewal) or returns a Stripe Checkout intent (when a charge is required, e.g. upgrade).
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 2 (subscription model), Step 7 (read API for "before" state). Step 11 (Stripe provider) is wired in Step 12 — until then, this endpoint returns a stub `{ "checkout_url": null, "status": "pending_payment_provider" }` for upgrade cases.

---

## Scope

One endpoint, the state-change logic, and the business rules for what's allowed. **No payment yet** — the endpoint is fully testable without Stripe. Step 12 plugs the Stripe Checkout call into the "needs payment" branch.

## Endpoint

| Endpoint | Auth | RBAC | Behaviour |
|---|---|---|---|
| `POST /api/v1/subscriptions/change` | authenticated | **Owner only** (enforced in Step 19's `billing.manage` permission key) | Computes the requested transition. For paid upgrades, returns a `checkout_intent` for the frontend to redirect into Stripe. For free transitions (downgrade, cycle switch on same tier), applies directly. |

### Request

```json
{
  "to_plan": "standard",            // required: target plan code
  "billing_cycle": "annual",         // required: 'monthly' | 'annual'
  "seats": 5                          // optional; defaults to current seats_purchased
}
```

### Response (4 cases)

**Case A — upgrade requiring payment (trial → paid, lower-tier → higher-tier):**
```json
{
  "outcome": "needs_payment",
  "checkout_url": "https://checkout.stripe.com/...",
  "checkout_session_id": "cs_test_...",
  "preview": {
    "to_plan": "standard",
    "billing_cycle": "annual",
    "amount_due_usd": 1392,
    "first_renewal_at": "2027-06-05T10:00:00Z"
  }
}
```

**Case B — downgrade (higher-tier → lower-tier):**
```json
{
  "outcome": "scheduled",
  "effective_at": "2026-07-05T10:00:00Z",   // next renewal — no mid-period refund
  "from_plan": "standard",
  "to_plan": "basic",
  "preview": {
    "amount_due_usd": 0,
    "remaining_period_credit": "kept until renewal"
  }
}
```

**Case C — billing-cycle change on same tier (monthly → annual or vice versa):**
- Monthly → annual: needs payment for the prorated annual difference → returns Case A shape.
- Annual → monthly: scheduled at next renewal → returns Case B shape.

**Case D — already on the requested plan + cycle + seats:**
```json
{ "outcome": "no_change" }
```

## Business rules

| Rule | Behaviour |
|---|---|
| Cannot change to `trial` from any paid plan | 400 — once you've paid, you don't go back to trial |
| Cannot change to `trial` even from trial | 400 — pointless |
| Cannot reduce `seats` below `seats_in_use` | 400 with the violating count, frontend must remove users first |
| Cannot reduce `seats` below `plan.included_seats` for the target plan | 400 — bundle minimum is 5 |
| Upgrade applies after payment success | Step 13 webhook flips subscription on `checkout.session.completed` |
| Downgrade applies at next renewal | This endpoint sets `subscription.next_plan_code`, `subscription.next_billing_cycle`, `subscription.next_seats`. A Celery task (delivered alongside Step 6's lifecycle) reads these at period boundary and applies them. |
| Read-only / archived orgs CAN call this endpoint | This is the recovery path. Read-only blocks all writes EXCEPT subscription change (Step 10 allow-list). |
| Cancelled subscriptions cannot change | 400 — must reactivate via a new sub (out of v1 scope; manual ops) |

## Schema additions

Need three new nullable columns on `subscriptions` for the "scheduled downgrade at renewal" pattern:

| Column | Type | Notes |
|---|---|---|
| `next_plan_code` | TEXT NULL | populated when a downgrade is scheduled |
| `next_billing_cycle` | TEXT NULL | populated when cycle change scheduled |
| `next_seats` | INTEGER NULL | populated when seat reduction scheduled |

Migration `00XX_subscriptions_scheduled_changes.py` — add the three columns, no backfill needed (all null until first scheduled change).

The lifecycle / period-rollover task (Step 6) reads these at period boundary and applies them, then clears them.

## Backend

`api/src/app/core/billing/service.py` — add:

```python
async def change_plan(
    session, org_id: UUID, to_plan: str, billing_cycle: str, seats: int | None,
    payment_provider: PaymentProvider | None  # None until Step 11/12 lands
) -> PlanChangeResponse:
    sub = await get_active_subscription(session, org_id)
    current_plan = plans.get(sub.plan_code)
    target_plan = plans.get(to_plan)  # raises if unknown

    # Apply business rules
    _validate_change(sub, current_plan, target_plan, billing_cycle, seats)

    # Decide outcome
    if (to_plan, billing_cycle, seats or sub.seats_purchased) == \
       (sub.plan_code, sub.billing_cycle, sub.seats_purchased):
        return PlanChangeResponse(outcome="no_change")

    if _is_upgrade(current_plan, target_plan, billing_cycle, sub.billing_cycle):
        if payment_provider is None:
            return PlanChangeResponse(outcome="needs_payment",
                                       checkout_url=None,
                                       checkout_session_id=None,
                                       preview=_preview(target_plan, billing_cycle, seats))
        checkout = await payment_provider.create_checkout_session(...)
        return PlanChangeResponse(outcome="needs_payment", **checkout, preview=...)
    else:
        # Downgrade or cycle-down: schedule
        sub.next_plan_code = to_plan
        sub.next_billing_cycle = billing_cycle
        sub.next_seats = seats
        return PlanChangeResponse(outcome="scheduled", effective_at=sub.current_period_end, ...)
```

`_is_upgrade` compares `monthly_bundle_usd` of current vs target with cycle weighting (annual is "higher" for the same tier in the sense that switching annual → monthly is a *downgrade* for our purposes).

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_subscriptions_scheduled_changes.py` | created |
| `api/src/app/core/billing/models.py` | modified — add `next_plan_code`, `next_billing_cycle`, `next_seats` to `Subscription` |
| `api/src/app/core/billing/router.py` | modified — `POST /subscriptions/change` |
| `api/src/app/core/billing/service.py` | modified — `change_plan`, `_validate_change`, `_is_upgrade`, `_preview` |
| `api/src/app/core/billing/schemas.py` | modified — `PlanChangeRequest`, `PlanChangeResponse` (Union of 4 cases via discriminated `outcome` field) |
| `api/src/app/core/billing/lifecycle.py` | modified — extend `transition_if_due` to apply `next_*` columns at period boundary |
| `api/tests/core/billing/test_plan_change_api.py` | created |

**7 files + 1 migration.** Within rule.

## Tests

`test_plan_change_api.py`:

- **Trial → Basic monthly:** `outcome='needs_payment'`, `preview.amount_due_usd=60`, `checkout_url=null` (no Stripe yet).
- **Trial → Standard annual:** `outcome='needs_payment'`, `preview.amount_due_usd=1392`.
- **Standard → Basic:** `outcome='scheduled'`, `effective_at = subscription.current_period_end`, subscription row has `next_plan_code='basic'`.
- **Basic monthly → Basic annual:** upgrade (paid difference) → `outcome='needs_payment'`, preview shows difference.
- **Standard annual → Standard monthly:** downgrade → `outcome='scheduled'`.
- **No-change call:** request matches current → `outcome='no_change'`.
- **Reducing seats below in-use:** seats=2 when 4 are active → 400 with `{"error": "seats_below_in_use", "in_use": 4, "min_allowed": 5}`.
- **Reducing seats below bundle minimum:** seats=3 on Basic (min=5) → 400 with `min_allowed=5`.
- **Cannot go to `trial`:** request `to_plan='trial'` → 400.
- **Cancelled sub cannot change:** seed cancelled → 400.
- **Read-only sub CAN change** (recovery path): seed read_only → 200 needs_payment.
- **Unknown `to_plan`:** request `to_plan='xyz'` → 422 (validation) or 404 with clear message.
- **Period-rollover applies `next_*`:** seed sub with `next_plan_code='basic'` and `current_period_end = now() - 1h`; run lifecycle scan; assert plan flipped to basic, `next_*` columns cleared.

## Smoke

```
.\API\docker-helper.cmd migrate
docker exec template_api-api-1 pytest tests/core/billing/test_plan_change_api.py -v

# Curl (as Owner of Ajay's Workspace):
TOKEN=...
curl -X POST http://localhost:8000/api/v1/subscriptions/change \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to_plan":"standard","billing_cycle":"monthly","seats":5}'
# → {"outcome":"needs_payment","checkout_url":null,"preview":{...}}
# (checkout_url stays null until Step 12)

# Schedule a downgrade:
curl -X POST http://localhost:8000/api/v1/subscriptions/change \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to_plan":"basic","billing_cycle":"monthly","seats":5}'
# → {"outcome":"scheduled","effective_at":"..."}
```

## Risks

- **"Upgrade vs downgrade" classification is plan-specific.** Defined by `monthly_bundle_usd` comparison. If two plans happen to have the same price (won't happen with current four, but defensively), the API should treat as no-change unless `seats` differ.
- **Cycle change pricing math.** Going monthly → annual mid-period: we need to charge the *difference* between what they've already paid (monthly bundle * partial period) and the annual bundle. Stripe Checkout's "proration" handles this — but during Step 8 (no Stripe), the preview is a best-effort estimate. Document that the preview number is final-amount-Stripe-bills, not a guarantee from our side.
- **`next_*` columns are mutually consistent.** If a user schedules a downgrade then changes their mind and schedules a different one, the new request overwrites the `next_*` fields (no audit trail of "you changed your mind twice"). Audit log emits `subscription.change_scheduled` and `subscription.change_rescheduled` so history exists.

## Rollback

Revert the 7 source files + downgrade the migration (drops the 3 `next_*` columns). Any scheduled downgrades in flight are lost — communicate before rolling back in production. For dev, no risk.
