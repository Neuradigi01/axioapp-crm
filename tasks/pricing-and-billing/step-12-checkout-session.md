# Step 12 — Checkout session endpoint

**Goal:** Wire the Step 11 `PaymentProvider` into the Step 8 (plan change) and Step 9 (seat change) flows so that "needs_payment" outcomes return a real Stripe Checkout URL. Also add `POST /api/v1/subscriptions/checkout` as a dedicated endpoint for the upgrade-from-banner flow that just needs a checkout URL for a chosen plan, no prior state-change required.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 8 (plan change API), Step 9 (seat management API), Step 11 (Stripe provider).

---

## Scope

Three integrations:

1. **Step 8's `change_plan`** — when outcome would be `needs_payment` and the provider is now available, call `payment_provider.create_checkout_session()` and return a real URL.
2. **Step 9's `change_seats`** — same pattern.
3. **New `POST /api/v1/subscriptions/checkout`** — direct "I want to upgrade to this plan, give me a checkout URL" endpoint. Used by:
   - The trial banner upgrade button (Step 15) when the user picks a plan from a quick modal
   - The public `/pricing` page's "Sign up" CTA which flows through register → auto-checkout for the chosen plan

## Endpoint: `POST /api/v1/subscriptions/checkout`

Request:
```json
{
  "to_plan": "standard",
  "billing_cycle": "monthly",
  "seats": 5,
  "success_url": "https://app.example.com/user/settings/billing?upgraded=true",
  "cancel_url": "https://app.example.com/user/settings/billing"
}
```

Response:
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_...",
  "session_id": "cs_test_..."
}
```

`success_url` and `cancel_url` are sent by the frontend, validated to be on an allow-listed domain (the app's own host — no open redirect). If not provided, defaults to `/user/settings/billing` paths under the request's origin.

The endpoint:

1. Validates the plan + cycle + seats per Step 8 / 9 rules.
2. Looks up or creates the org's `stripe_customer_id` (calls `payment_provider.create_customer` if null, then stores).
3. Calls `payment_provider.create_checkout_session(...)` with the resolved customer + line items.
4. Persists the `session_id` in a new column on `subscriptions` (`pending_checkout_session_id`) so Step 13's webhook can correlate.
5. Returns the URL.

## Schema addition

One nullable column on `subscriptions`:

| Column | Type | Notes |
|---|---|---|
| `pending_checkout_session_id` | TEXT NULL | most recent Stripe session ID created for this org; webhook clears it when session completes/expires |

Migration `00XX_subscriptions_pending_checkout.py`.

## Wiring into Step 8 / 9

`api/src/app/core/billing/router.py` — the existing handlers from Steps 8 and 9 now inject `PaymentProvider` and pass it into the service:

```python
@router.post("/subscriptions/change")
async def change_plan(
    body: PlanChangeRequest,
    org_id = Depends(get_current_org_id),
    session = Depends(get_session),
    provider = Depends(get_payment_provider),
):
    return await billing_service.change_plan(
        session, org_id,
        to_plan=body.to_plan, billing_cycle=body.billing_cycle, seats=body.seats,
        payment_provider=provider,
    )
```

The `payment_provider=None` branch from Step 8 is now removed — the provider is always present.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_subscriptions_pending_checkout.py` | created |
| `api/src/app/core/billing/models.py` | modified — add `pending_checkout_session_id` |
| `api/src/app/core/billing/router.py` | modified — `POST /subscriptions/checkout`; wire provider into change/seats |
| `api/src/app/core/billing/service.py` | modified — `create_direct_checkout`, customer-lookup-or-create helper |
| `api/src/app/core/billing/schemas.py` | modified — `CheckoutRequest`, `CheckoutResponse` |
| `api/tests/core/billing/test_checkout_endpoint.py` | created |

**6 files + 1 migration.** Within rule.

## Tests

`test_checkout_endpoint.py` (mock the Stripe provider):

- **Direct checkout creates a session:** POST `/subscriptions/checkout` with valid body → 200, `checkout_url` is a string, `session_id` set, `subscription.pending_checkout_session_id` updated.
- **Customer created on first checkout:** subscription has `stripe_customer_id=null` → after checkout, it's populated.
- **Customer reused on second checkout:** subsequent checkout does not create a new customer; calls Stripe.Customer.create exactly once.
- **Plan change with provider returns real URL:** POST `/subscriptions/change` with Trial → Standard → response.checkout_url is a Stripe URL (mocked).
- **Seat increase with provider returns real URL:** POST `/subscriptions/seats` adding seats on a paid sub → response.checkout_url is a Stripe URL.
- **Downgrade does not call provider:** POST `/subscriptions/change` Standard → Basic → `outcome='scheduled'`, provider not called (assert via mock).
- **Same-plan no-change does not call provider:** `outcome='no_change'`, provider not called.
- **Invalid success_url (off-domain) rejected:** `success_url="https://evil.com"` → 400 invalid_redirect.
- **Default URLs used when omitted:** omit success_url/cancel_url → defaults applied.
- **Validation errors propagate from Steps 8/9:** seats below minimum → 400 unchanged.

## Smoke

```
.\API\docker-helper.cmd migrate

# Need real Stripe test keys from Step 11 + seeded prices.
# Run seed first if not already done:
docker exec template_api-api-1 uv run python -m app.scripts.seed_stripe_catalog

# Now hit checkout:
TOKEN=...
curl -X POST http://localhost:8000/api/v1/subscriptions/checkout \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "to_plan": "standard",
    "billing_cycle": "monthly",
    "seats": 5,
    "success_url": "http://localhost:4200/user/settings/billing?upgraded=true",
    "cancel_url": "http://localhost:4200/user/settings/billing"
  }'

# → {"checkout_url":"https://checkout.stripe.com/c/pay/cs_test_...","session_id":"cs_test_..."}

# Open the URL in a browser — Stripe-hosted checkout page renders with Standard $145/mo line item.
# Pay with test card 4242 4242 4242 4242, any future expiry, any CVC, any ZIP.
# → Redirects to success_url.
# → Webhook in Step 13 will flip the subscription to active (not yet wired in this step).

# DB check:
SELECT plan_code, status, pending_checkout_session_id, stripe_customer_id
FROM subscriptions WHERE org_id = '41f9ede9-41b3-44ce-b489-3004566d4068';
# → still trialing, pending_checkout_session_id set, stripe_customer_id set.
# (status flips after Step 13 webhook.)
```

## Risks

- **`success_url` open-redirect.** Allow-list it to the app's own host(s). For dev, allow `localhost:4200` and `localhost:8000`. For prod, env-driven allow-list.
- **Checkout session expires in 24 hours** (Stripe default). If the user bookmarks the URL and returns later, it 404s. UX: always start a fresh checkout from the upgrade modal — don't link to old session URLs.
- **Multiple concurrent checkouts.** If a user clicks Upgrade twice quickly, two Checkout Sessions exist. `pending_checkout_session_id` stores only the most recent. The first one completes → webhook fires → subscription upgrades. The second one's payment is then a "completed for an already-active subscription" event — Step 13's webhook handles this as a dedup case (issues a refund via Stripe Dashboard manually, or silently ignores).
- **Tax handling.** Not in scope for v1. Stripe Checkout has an `automatic_tax` flag that can be enabled later. Document the deferral.
- **Currency lock.** Stripe Checkout sessions are currency-locked. Since we're USD-only for v1, all Prices are USD-denominated.

## Rollback

Revert the 6 files + downgrade the migration. The `pending_checkout_session_id` column drops cleanly. Any Stripe Checkout Sessions in flight at rollback time complete on Stripe's side but the webhook handler (Step 13) won't know how to reconcile — handle manually if it happens.
