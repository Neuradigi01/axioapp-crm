"""Stripe implementation of `PaymentProvider`.

The Stripe Python SDK is synchronous; every call is wrapped in
`asyncio.to_thread` so route handlers do not block the event loop on
network IO to api.stripe.com.

The (plan_code, billing_cycle) → Stripe Price ID lookup is loaded once
from `stripe_price_map.yaml` at construction time. The map is the
source of truth — any direct edit to a Price in the Stripe dashboard
will silently drift from this YAML. Operators regenerate the map by
running `python -m app.scripts.seed_stripe_catalog` (Step 11's seed
script); see the file header for the bootstrap procedure.

The `stripe` SDK is imported lazily via `_stripe_module()` so the test
suite can monkeypatch the module without installing the SDK in CI.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import yaml

from src.app.core.subscriptions.payment_provider import CheckoutSessionResult

log = logging.getLogger(__name__)


class StripePriceMapMissing(RuntimeError):
    """Raised when the YAML price map is missing or incomplete.

    Includes a remediation hint pointing at the seed script so
    operators can recover without spelunking through the SDK.
    """


class InvalidWebhookSignature(RuntimeError):
    """Raised when Stripe's webhook signature verification fails.

    Step 13's webhook handler catches this and returns 400 — we do not
    leak Stripe's error text to the wire to avoid signal that could
    help an attacker tune a forged-signature attempt.
    """


def _stripe_module():
    """Import-time decoupling for the test suite.

    Production calls return the real `stripe` module; tests
    monkeypatch this function to return a `MagicMock` so the SDK is
    never instantiated against a real API key.
    """
    import stripe  # noqa: PLC0415 — intentional lazy import

    return stripe


def _default_price_map_path() -> Path:
    """Path the seed script writes to and the provider loads from."""
    return (
        Path(__file__).resolve().parent.parent / "stripe_price_map.yaml"
    )


class StripeProvider:
    """Concrete `PaymentProvider` for Stripe."""

    def __init__(
        self,
        secret_key: str,
        webhook_secret: str,
        price_map_path: Path | None = None,
    ) -> None:
        self._stripe = _stripe_module()
        self._stripe.api_key = secret_key
        self._webhook_secret = webhook_secret
        self._price_map_path = price_map_path or _default_price_map_path()
        self._price_map: dict[str, dict[str, str]] = self._load_price_map()

    # ---- internals ---------------------------------------------------------

    def _load_price_map(self) -> dict[str, dict[str, str]]:
        if not self._price_map_path.exists():
            raise StripePriceMapMissing(
                f"Stripe price map not found at {self._price_map_path}. "
                f"Run `python -m app.scripts.seed_stripe_catalog` to create it."
            )
        with self._price_map_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise StripePriceMapMissing(
                f"Stripe price map at {self._price_map_path} is malformed; "
                "expected a top-level mapping."
            )
        return data

    def _resolve_price_id(
        self, plan_code: str, billing_cycle: str,
    ) -> str:
        plan_entry = self._price_map.get(plan_code) or {}
        price_id = plan_entry.get(billing_cycle)
        if not price_id or price_id.startswith("REPLACE_ME_"):
            raise StripePriceMapMissing(
                f"No Stripe Price configured for {plan_code}/{billing_cycle}. "
                f"Re-run the seed script to populate."
            )
        return price_id

    # ---- protocol ----------------------------------------------------------

    async def create_customer(
        self, org_id: uuid.UUID, email: str, name: str,
    ) -> str:
        result = await asyncio.to_thread(
            self._stripe.Customer.create,
            email=email,
            name=name,
            metadata={"org_id": str(org_id)},
        )
        return result["id"]

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
        price_id = self._resolve_price_id(plan_code, billing_cycle)
        kwargs: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": seats}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            # All four keys land on the webhook event so Step 13 can
            # reconcile the local subscription row without a separate
            # state-lookup round-trip.
            "metadata": {
                "org_id": str(org_id),
                "plan_code": plan_code,
                "billing_cycle": billing_cycle,
                "seats": str(seats),
            },
        }
        if customer_id is not None:
            kwargs["customer"] = customer_id
        session = await asyncio.to_thread(
            self._stripe.checkout.Session.create, **kwargs,
        )
        return CheckoutSessionResult(
            url=session["url"],
            session_id=session["id"],
            customer_id=session["customer"],
        )

    async def update_subscription(
        self,
        provider_subscription_id: str,
        plan_code: str | None = None,
        billing_cycle: str | None = None,
        seats: int | None = None,
    ) -> None:
        # Stripe's `Subscription.modify` cannot take `quantity` at the
        # top level — quantity lives on subscription items. Fetch the
        # active subscription to discover the item ID, then rewrite it.
        sub = await asyncio.to_thread(
            self._stripe.Subscription.retrieve, provider_subscription_id,
        )
        items = sub["items"]["data"]
        if not items:
            raise RuntimeError(
                f"Stripe subscription {provider_subscription_id} has no items "
                "to update."
            )
        item = items[0]
        modified_item: dict[str, Any] = {"id": item["id"]}
        if plan_code is not None and billing_cycle is not None:
            modified_item["price"] = self._resolve_price_id(
                plan_code, billing_cycle,
            )
        if seats is not None:
            modified_item["quantity"] = seats
        await asyncio.to_thread(
            self._stripe.Subscription.modify,
            provider_subscription_id,
            items=[modified_item],
        )

    async def cancel_subscription(
        self, provider_subscription_id: str,
    ) -> None:
        # Cancel at period end — the customer keeps access through the
        # paid period and Step 13's webhook flips the local row when
        # the period actually ends.
        await asyncio.to_thread(
            self._stripe.Subscription.modify,
            provider_subscription_id,
            cancel_at_period_end=True,
        )

    async def verify_webhook(
        self, payload: bytes, signature: str,
    ) -> dict[str, Any]:
        try:
            event = await asyncio.to_thread(
                self._stripe.Webhook.construct_event,
                payload,
                signature,
                self._webhook_secret,
            )
        except Exception as exc:  # noqa: BLE001 — SDK's exception type varies
            # Do NOT pass `exc` text to the response; that's diagnostic
            # only. The Step 13 handler maps this to a 400.
            log.warning(
                "Stripe webhook signature verification failed: %s", exc,
            )
            raise InvalidWebhookSignature("invalid signature") from exc
        return dict(event)
