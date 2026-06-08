"""Seed Stripe Products and Prices from `plans.yaml`.

The Stripe catalogue is the *operator's* responsibility — Checkout
cannot create a Price on the fly. This script bootstraps the catalogue
for a fresh Stripe account and refreshes the local price map
(`stripe_price_map.yaml`) that the `StripeProvider` consumes.

Idempotency
-----------
The script matches existing Stripe objects by metadata:

  - `Product` is keyed by `metadata.plan_code` (the plan code from
    plans.yaml).
  - `Price` is keyed by `metadata.plan_code` + `metadata.billing_cycle`.

A second run against the same Stripe account is a no-op on the
Stripe side and produces the same YAML.

Pricing model
-------------
Each (plan, cycle) Price uses Stripe's "tiered" billing scheme so the
bundle minimum is enforced server-side at Stripe:

  - Tier 1: `flat_amount = bundle_cents`, `up_to = included_seats`
  - Tier 2: `unit_amount = extra_seat_cents`, `up_to = inf`

This way a Checkout for 7 seats on Basic monthly bills $60 + 2 × $12
= $84 without our code doing any of the math.

Usage
-----
    export STRIPE_SECRET_KEY=sk_test_...
    python -m app.scripts.seed_stripe_catalog

The script writes the IDs to `app/core/subscriptions/stripe_price_map.yaml`.
Commit that file after a fresh seed; runtime reads it.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from src.app.core.subscriptions import plans as plans_module

log = logging.getLogger(__name__)


# Resolved here (not as a constant import from the provider) so the
# seed script has no runtime dependency on `stripe_provider.py`.
_PRICE_MAP_PATH: Path = (
    Path(__file__).resolve().parent.parent
    / "core" / "subscriptions" / "stripe_price_map.yaml"
)


# Cycle name on our side → Stripe's `recurring.interval` value.
_CYCLE_TO_INTERVAL: dict[str, str] = {"monthly": "month", "annual": "year"}


def _stripe_module():
    """Lazy import so tests can monkeypatch the SDK without installing it."""
    import stripe  # noqa: PLC0415

    return stripe


def _metadata_value(obj, key: str) -> str | None:
    """Read `obj.metadata[key]` off a Stripe object safely.

    Stripe SDK ≥ 5 ships `StripeObject` with a custom `__getattr__`
    that shadows the inherited `dict.get`, and `dict(stripe_object)`
    triggers a broken iteration. Bracket access via `__getitem__` is
    the only reliable read path — wrapped here in try/except so an
    absent `metadata` field returns `None` rather than crashing.
    """
    try:
        md = obj["metadata"]
    except (KeyError, TypeError):
        return None
    if md is None:
        return None
    try:
        value = md[key]
    except (KeyError, TypeError):
        return None
    return value


def _find_existing_product(
    stripe_sdk, plan_code: str,
) -> str | None:
    """Match by `metadata.plan_code`. Returns the Stripe Product ID or `None`."""
    for product in stripe_sdk.Product.list(limit=100).auto_paging_iter():
        if _metadata_value(product, "plan_code") == plan_code:
            return product["id"]
    return None


def _find_existing_price(
    stripe_sdk, product_id: str, plan_code: str, billing_cycle: str,
) -> str | None:
    """Match by Product + (plan_code, billing_cycle) metadata pair."""
    listing = stripe_sdk.Price.list(product=product_id, limit=100)
    for price in listing.auto_paging_iter():
        if (
            _metadata_value(price, "plan_code") == plan_code
            and _metadata_value(price, "billing_cycle") == billing_cycle
        ):
            return price["id"]
    return None


def _ensure_product(stripe_sdk, plan: plans_module.Plan) -> str:
    existing = _find_existing_product(stripe_sdk, plan.code)
    if existing is not None:
        log.info("Product for %r already exists: %s", plan.code, existing)
        return existing
    created = stripe_sdk.Product.create(
        name=f"FurnitureCRM — {plan.name}",
        metadata={"plan_code": plan.code},
    )
    log.info("Created Product for %r: %s", plan.code, created["id"])
    return created["id"]


def _ensure_price(
    stripe_sdk, product_id: str, plan: plans_module.Plan, billing_cycle: str,
) -> str:
    existing = _find_existing_price(
        stripe_sdk, product_id, plan.code, billing_cycle,
    )
    if existing is not None:
        log.info(
            "Price for %r/%r already exists: %s",
            plan.code, billing_cycle, existing,
        )
        return existing

    if billing_cycle == "monthly":
        bundle_cents = plan.pricing.monthly_bundle_cents
        extra_seat_cents = plan.pricing.extra_seat_monthly_cents
    else:
        bundle_cents = plan.pricing.annual_bundle_cents
        extra_seat_cents = plan.pricing.extra_seat_annual_cents

    created = stripe_sdk.Price.create(
        product=product_id,
        currency="usd",
        recurring={
            "interval": _CYCLE_TO_INTERVAL[billing_cycle],
            "usage_type": "licensed",
        },
        billing_scheme="tiered",
        tiers_mode="graduated",
        tiers=[
            {
                "flat_amount": bundle_cents,
                "up_to": plan.pricing.included_seats,
            },
            {"unit_amount": extra_seat_cents, "up_to": "inf"},
        ],
        metadata={
            "plan_code": plan.code,
            "billing_cycle": billing_cycle,
        },
    )
    log.info(
        "Created Price for %r/%r: %s",
        plan.code, billing_cycle, created["id"],
    )
    return created["id"]


def run(
    stripe_sdk: Any | None = None,
    output_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Seed Stripe and write the price map. Returns the resulting map.

    `stripe_sdk` is injectable so tests can pass a `MagicMock` without
    monkeypatching the import. `output_path` is similarly injectable
    so tests write to a tmp file.
    """
    sdk = stripe_sdk if stripe_sdk is not None else _stripe_module()
    if not sdk.api_key:
        sdk.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not sdk.api_key:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is required (set the env var or call "
            "`stripe.api_key = ...` before invoking run())."
        )

    target_path = output_path or _PRICE_MAP_PATH
    price_map: dict[str, dict[str, str]] = {}

    # Public plans only; trial has no Stripe-side artefact.
    for plan in plans_module.public():
        product_id = _ensure_product(sdk, plan)
        price_map[plan.code] = {
            "monthly": _ensure_price(sdk, product_id, plan, "monthly"),
            "annual": _ensure_price(sdk, product_id, plan, "annual"),
        }

    with target_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(price_map, f, default_flow_style=False, sort_keys=True)
    log.info("Wrote %d plans to %s", len(price_map), target_path)
    return price_map


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run()
    except Exception:  # pragma: no cover — operator-facing CLI
        log.exception("Stripe seed failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
