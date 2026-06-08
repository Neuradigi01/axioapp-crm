"""Payment provider abstraction — Step 11.

Step 12 (checkout) and Step 13 (webhooks) consume this protocol; the
v1 implementation is `StripeProvider` under `providers/`. The interface
is intentionally narrow so a second provider (Razorpay, Paddle, …) can
slot in without touching call sites.

All methods are `async` — the underlying Stripe SDK is sync but the
adapter wraps blocking calls in `asyncio.to_thread` so route handlers
do not block the event loop on Stripe IO.

`CheckoutSessionResult` is the only DTO returned by the protocol; the
rest return either the provider ID (str) or `None`. Webhook events
return raw `dict` because the upstream payload shape is provider-
specific and each consumer (Step 13) decodes the keys it needs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CheckoutSessionResult:
    """The hand-off the frontend needs to redirect into Stripe Checkout.

    - `url`: the hosted Checkout page the user is redirected to.
    - `session_id`: identifies the Checkout Session for later
      webhook reconciliation (Step 13).
    - `customer_id`: the provider Customer ID, persisted on the
      `subscriptions` row so subsequent renewals/cancels can target it.
    """

    url: str
    session_id: str
    customer_id: str


class PaymentProvider(Protocol):
    """Abstract payment integration; runtime checked structurally."""

    async def create_customer(
        self, org_id: uuid.UUID, email: str, name: str,
    ) -> str:
        """Create a Customer in the provider's system.

        Returns the provider's customer ID. Callers persist this on the
        `subscriptions` row so future API calls (subscription update,
        cancel) can reference it without round-tripping through
        Checkout.
        """
        ...

    async def create_checkout_session(
        self,
        org_id: uuid.UUID,
        customer_id: str | None,
        plan_code: str,
        billing_cycle: str,
        seats: int,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSessionResult:
        """Build a Checkout Session for the requested plan + cycle + seats.

        `customer_id` may be `None` when the org has never paid before;
        the provider creates a fresh Customer during Checkout and
        returns the ID on the result.

        `success_url` and `cancel_url` are the FurnitureCRM frontend
        URLs the provider redirects to after the user completes / aborts
        the hosted Checkout flow.
        """
        ...

    async def update_subscription(
        self,
        provider_subscription_id: str,
        plan_code: str | None = None,
        billing_cycle: str | None = None,
        seats: int | None = None,
    ) -> None:
        """Apply a change to an active subscription.

        Used for mid-period adjustments (seat additions, paid cycle
        switches). Unset arguments are not modified. The provider
        decides the proration policy; the caller does not.
        """
        ...

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        """Cancel at the end of the current period.

        The customer keeps access through the paid period; the
        provider's webhook fires when the period ends and Step 13's
        handler flips the local row to `cancelled`.
        """
        ...

    async def verify_webhook(
        self, payload: bytes, signature: str,
    ) -> dict[str, Any]:
        """Validate the provider's webhook signature.

        Raises on an invalid signature. On success, returns the parsed
        event dict — the caller dispatches on `event["type"]`.
        """
        ...
