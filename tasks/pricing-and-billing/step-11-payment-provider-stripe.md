# Step 11 — Payment provider abstraction (Stripe)

**Goal:** A `PaymentProvider` Python protocol with a concrete `StripeProvider` implementation. Step 12 (checkout) and Step 13 (webhooks) consume this abstraction. The interface is designed so Razorpay can be slotted in as `RazorpayProvider` later without touching call sites.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 2 (subscription model — the provider stores `stripe_customer_id` / `stripe_subscription_id`). Step 1 (plan registry — provider needs plan prices to map to Stripe price IDs).

---

## Scope

The protocol, the Stripe implementation, a Stripe customer-creation flow, and the Stripe-side price/product seed script. **No HTTP routes in this step** — Step 12 mounts the routes that call into the provider.

## The protocol

`api/src/app/core/billing/payment_provider.py`:

```python
class PaymentProvider(Protocol):
    """
    Abstract payment integration. Stripe is the v1 implementation;
    Razorpay can be added later by implementing this same protocol.
    """

    async def create_customer(
        self, org_id: UUID, email: str, name: str
    ) -> str:
        """Create a Customer in the provider's system. Returns provider customer ID."""

    async def create_checkout_session(
        self,
        org_id: UUID,
        customer_id: str | None,         # None if creating customer at checkout time
        plan_code: str,
        billing_cycle: str,
        seats: int,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSessionResult:
        """
        Build a Checkout Session for the requested plan + cycle + seats.
        Returns the URL the user is redirected to and the session ID for
        later webhook reconciliation.
        """

    async def update_subscription(
        self,
        provider_subscription_id: str,
        plan_code: str | None = None,
        billing_cycle: str | None = None,
        seats: int | None = None,
    ) -> None:
        """Apply a change to an active subscription (e.g. add seats mid-period)."""

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        """Cancel at end of current period."""

    async def verify_webhook(self, payload: bytes, signature: str) -> dict:
        """Verify webhook signature; raise on invalid; return parsed event dict."""


@dataclass
class CheckoutSessionResult:
    url: str
    session_id: str
    customer_id: str
```

## StripeProvider implementation

`api/src/app/core/billing/providers/stripe_provider.py`:

```python
class StripeProvider:
    def __init__(self, secret_key: str, webhook_secret: str):
        self._stripe = stripe
        self._stripe.api_key = secret_key
        self._webhook_secret = webhook_secret

    async def create_customer(self, org_id, email, name) -> str:
        result = await asyncio.to_thread(
            self._stripe.Customer.create,
            email=email, name=name, metadata={"org_id": str(org_id)},
        )
        return result["id"]

    async def create_checkout_session(...) -> CheckoutSessionResult:
        price_id = _resolve_stripe_price(plan_code, billing_cycle)
        # Bundle uses Stripe "tiered" pricing: flat for bundle, per-unit for overage.
        # See plans.yaml mapping table below.
        session = await asyncio.to_thread(
            self._stripe.checkout.Session.create,
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": seats}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"org_id": str(org_id), "plan_code": plan_code, "billing_cycle": billing_cycle, "seats": seats},
        )
        return CheckoutSessionResult(url=session.url, session_id=session.id, customer_id=session.customer)

    # ... other methods
```

The `stripe` Python SDK is sync; calls are wrapped in `asyncio.to_thread` to keep them off the event loop.

## Stripe Product / Price seeding

Stripe requires `Product` and `Price` objects to exist before Checkout can reference them. A one-time admin script seeds them:

`api/src/app/scripts/seed_stripe_catalog.py`:

```python
"""
Idempotent. Reads plans.yaml. For each paid plan, creates/updates:
  - One Product per plan ("FurnitureCRM — Basic")
  - One Price per (plan, billing_cycle) using Stripe tiered pricing model

Tiered pricing example for Basic monthly:
  - First 5 units: flat $60 (the bundle)
  - Beyond: $12/unit (overage)

Saves the resulting price IDs to a stripe_price_map.yaml committed to the repo
(no secrets, just IDs like price_1abc...). The StripeProvider reads this map.
"""
```

Run during deployment / setup:

```
docker exec template_api-api-1 uv run python -m app.scripts.seed_stripe_catalog
```

`stripe_price_map.yaml` example:

```yaml
basic:
  monthly: price_1AbcMonthlyBasic
  annual: price_1AbcAnnualBasic
standard:
  monthly: price_1AbcMonthlyStandard
  annual: price_1AbcAnnualStandard
enterprise:
  monthly: price_1AbcMonthlyEnt
  annual: price_1AbcAnnualEnt
```

## Configuration

`api/src/app/shared/config.py` — extend with:

| Setting | env var | Default | Notes |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | `STRIPE_SECRET_KEY` | required | `sk_test_...` for dev, `sk_live_...` for prod |
| `STRIPE_PUBLISHABLE_KEY` | `STRIPE_PUBLISHABLE_KEY` | required | passed to frontend |
| `STRIPE_WEBHOOK_SECRET` | `STRIPE_WEBHOOK_SECRET` | required | `whsec_...` |
| `STRIPE_PRICE_MAP_PATH` | `STRIPE_PRICE_MAP_PATH` | `app/core/billing/stripe_price_map.yaml` | path to the map |

These go into `.env.example` per CLAUDE.md ops convention.

## Dependency injection

`api/src/app/core/billing/dependencies.py`:

```python
@lru_cache
def get_payment_provider() -> PaymentProvider:
    settings = get_settings()
    return StripeProvider(
        secret_key=settings.STRIPE_SECRET_KEY,
        webhook_secret=settings.STRIPE_WEBHOOK_SECRET,
    )
```

Routes (Steps 12, 13) inject this as a FastAPI dependency.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/payment_provider.py` | created — Protocol + `CheckoutSessionResult` |
| `api/src/app/core/billing/providers/__init__.py` | created |
| `api/src/app/core/billing/providers/stripe_provider.py` | created |
| `api/src/app/core/billing/stripe_price_map.yaml` | created (after running seed script) |
| `api/src/app/scripts/seed_stripe_catalog.py` | created |
| `api/src/app/shared/config.py` | modified — Stripe env vars |
| `api/src/app/core/billing/dependencies.py` | modified — `get_payment_provider` |
| `api/pyproject.toml` | modified — add `stripe>=10.0.0` dependency |
| `.env.example` | modified — add Stripe vars |
| `api/tests/core/billing/test_stripe_provider.py` | created — mocked Stripe SDK |

**10 files.** At the edge of the per-step rule — defensible because much of it is config/scripting glue with little logic.

## Tests

`test_stripe_provider.py`:

- **`create_customer` calls Stripe with correct args:** mock `stripe.Customer.create`, call provider, assert email/name/metadata passed through.
- **`create_checkout_session` uses tiered pricing:** mock checkout creation, assert `line_items[0].price` resolves to the right ID from the price map and `quantity` equals seats.
- **`create_checkout_session` includes metadata:** assert `metadata` carries `org_id`, `plan_code`, `billing_cycle`, `seats` (needed for the webhook to reconcile).
- **`verify_webhook` rejects bad signature:** signature mismatch → raises.
- **`verify_webhook` accepts valid signature:** signed with the configured secret → returns parsed event.
- **`update_subscription` calls Stripe update with quantity change:** asserts the right kwargs reach `stripe.Subscription.modify`.
- **`cancel_subscription` cancels at period end:** asserts `cancel_at_period_end=True` is set.
- **Seed script is idempotent:** running twice does not create duplicate Products or Prices.
- **Price map persists across runs:** running seed writes to YAML; loading the YAML in a fresh process returns the same IDs.

## Smoke

```
# 1. Get a Stripe test secret key from dashboard.stripe.com/test
# 2. Set env vars:
$env:STRIPE_SECRET_KEY="sk_test_..."
$env:STRIPE_PUBLISHABLE_KEY="pk_test_..."
$env:STRIPE_WEBHOOK_SECRET="whsec_..."

# 3. Restart container to pick up env:
.\API\docker-helper.cmd restart

# 4. Run seed script:
docker exec template_api-api-1 uv run python -m app.scripts.seed_stripe_catalog
# → 6 Stripe Prices created (3 plans × 2 cycles), IDs written to stripe_price_map.yaml.
# → Visible in Stripe Dashboard → Products.

# 5. Run unit tests with mocked SDK:
docker exec template_api-api-1 pytest tests/core/billing/test_stripe_provider.py -v
```

## Risks

- **Stripe SDK is synchronous.** Wrapping in `asyncio.to_thread` is correct but adds ~1ms overhead per call. Fine for billing endpoints (low-frequency).
- **Tiered pricing setup in Stripe is non-obvious.** The seed script uses `Price.create_with_tiers(...)` shape: tier 1 = `flat_amount=6000` (cents) for `up_to=5`, tier 2 = `unit_amount=1200` for `up_to=inf`. Test this in Stripe Test mode before relying on it; the math must match our preview from Step 9.
- **Price map drift.** If someone edits a Price directly in Stripe Dashboard, our YAML becomes stale. Mitigation: the seed script is the source of truth; document "do not edit Prices in Stripe Dashboard directly" in the operations runbook.
- **Webhook signing secret rotation.** Stripe lets you have multiple active secrets during rotation. For v1, we accept only one — document the rotation procedure (set new secret, redeploy, delete old in Stripe).
- **`stripe` SDK version pinning.** Stripe occasionally renames API parameters in major versions. Pin to a known-good version; bump deliberately.

## Rollback

Revert the 10 files. Delete the Stripe Products/Prices in Stripe Dashboard (or leave them — they're harmless once unreferenced). Any in-flight Checkout Sessions still complete in Stripe; the webhook in Step 13 reconciles them as orphan events that get ignored (we no longer have a code path to handle them, so they sit unprocessed — review and clean up in Stripe Dashboard).
