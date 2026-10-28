"""Tests for `StripeProvider` and the catalogue seed script (Step 11).

Strategy:
  - The Stripe Python SDK is replaced with a `MagicMock` via the
    `_stripe_module()` indirection that both the provider and the
    seed script use. Nothing in this file touches a real Stripe
    account.
  - The YAML price map is generated in `tmp_path` for each test so
    the on-disk fixture cannot leak between cases.

Coverage matches the spec's acceptance list — argument shape on
create_customer / create_checkout_session, webhook signature handling,
update_subscription and cancel_subscription kwarg shape, and seed
script idempotency + persistence.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.app.core.subscriptions.payment_provider import CheckoutSessionResult
from src.app.core.subscriptions.providers.stripe_provider import (
    InvalidWebhookSignature,
    StripePriceMapMissing,
    StripeProvider,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FAKE_PRICE_MAP = {
    "basic": {
        "monthly": "price_basic_monthly_fake",
        "annual": "price_basic_annual_fake",
    },
    "standard": {
        "monthly": "price_standard_monthly_fake",
        "annual": "price_standard_annual_fake",
    },
    "enterprise": {
        "monthly": "price_enterprise_monthly_fake",
        "annual": "price_enterprise_annual_fake",
    },
}


@pytest.fixture
def fake_price_map(tmp_path) -> Path:
    path = tmp_path / "prices.yaml"
    path.write_text(yaml.safe_dump(_FAKE_PRICE_MAP), encoding="utf-8")
    return path


@pytest.fixture
def mock_stripe(monkeypatch) -> MagicMock:
    """Replace the SDK lookup in the provider module."""
    mock = MagicMock(name="stripe")
    monkeypatch.setattr(
        "src.app.core.subscriptions.providers.stripe_provider._stripe_module",
        lambda: mock,
    )
    return mock


@pytest.fixture
def provider(mock_stripe, fake_price_map) -> StripeProvider:
    return StripeProvider(
        secret_key="sk_test_xxx",
        webhook_secret="whsec_xxx",
        price_map_path=fake_price_map,
    )


# ---------------------------------------------------------------------------
# create_customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_customer_passes_email_name_metadata(
    provider,
    mock_stripe,
):
    mock_stripe.Customer.create.return_value = {"id": "cus_123"}
    org_id = uuid.uuid4()

    customer_id = await provider.create_customer(
        org_id,
        "alice@example.com",
        "Alice",
    )

    assert customer_id == "cus_123"
    mock_stripe.Customer.create.assert_called_once()
    kwargs = mock_stripe.Customer.create.call_args.kwargs
    assert kwargs["email"] == "alice@example.com"
    assert kwargs["name"] == "Alice"
    assert kwargs["metadata"] == {"org_id": str(org_id)}


# ---------------------------------------------------------------------------
# create_checkout_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checkout_session_uses_mapped_price_and_quantity(
    provider,
    mock_stripe,
):
    mock_stripe.checkout.Session.create.return_value = {
        "url": "https://checkout.stripe.com/c/pay/cs_test_123",
        "id": "cs_test_123",
        "customer": "cus_456",
    }
    org_id = uuid.uuid4()

    result = await provider.create_checkout_session(
        org_id=org_id,
        customer_id="cus_456",
        plan_code="basic",
        billing_cycle="monthly",
        seats=5,
        success_url="https://example.com/ok",
        cancel_url="https://example.com/no",
    )

    assert isinstance(result, CheckoutSessionResult)
    assert result.url.startswith("https://checkout.stripe.com")
    assert result.session_id == "cs_test_123"
    assert result.customer_id == "cus_456"

    kwargs = mock_stripe.checkout.Session.create.call_args.kwargs
    assert kwargs["mode"] == "subscription"
    assert kwargs["line_items"] == [
        {"price": "price_basic_monthly_fake", "quantity": 5},
    ]
    assert kwargs["customer"] == "cus_456"


@pytest.mark.asyncio
async def test_create_checkout_session_carries_reconciliation_metadata(
    provider,
    mock_stripe,
):
    """Step 13's webhook decoder reads these four metadata keys to
    locate the org and apply the right plan / cycle / seats. Missing
    keys would silently drop subscriptions."""
    mock_stripe.checkout.Session.create.return_value = {
        "url": "u",
        "id": "cs",
        "customer": "cus",
    }
    org_id = uuid.uuid4()

    await provider.create_checkout_session(
        org_id=org_id,
        customer_id=None,
        plan_code="standard",
        billing_cycle="annual",
        seats=8,
        success_url="https://example.com/ok",
        cancel_url="https://example.com/no",
    )

    metadata = mock_stripe.checkout.Session.create.call_args.kwargs["metadata"]
    assert metadata == {
        "org_id": str(org_id),
        "plan_code": "standard",
        "billing_cycle": "annual",
        "seats": "8",
    }


@pytest.mark.asyncio
async def test_create_checkout_session_unmapped_plan_raises(
    provider,
):
    with pytest.raises(StripePriceMapMissing):
        await provider.create_checkout_session(
            org_id=uuid.uuid4(),
            customer_id="cus",
            plan_code="ghost",
            billing_cycle="monthly",
            seats=5,
            success_url="u",
            cancel_url="u",
        )


# ---------------------------------------------------------------------------
# verify_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_webhook_returns_parsed_event_on_valid_signature(
    provider,
    mock_stripe,
):
    mock_stripe.Webhook.construct_event.return_value = {
        "id": "evt_1",
        "type": "checkout.session.completed",
    }
    event = await provider.verify_webhook(b"{}", "t=1,v1=abc")
    assert event["type"] == "checkout.session.completed"
    mock_stripe.Webhook.construct_event.assert_called_once_with(
        b"{}",
        "t=1,v1=abc",
        "whsec_xxx",
    )


@pytest.mark.asyncio
async def test_verify_webhook_raises_on_bad_signature(provider, mock_stripe):
    mock_stripe.Webhook.construct_event.side_effect = RuntimeError("nope")
    with pytest.raises(InvalidWebhookSignature):
        await provider.verify_webhook(b"{}", "bad")


# ---------------------------------------------------------------------------
# update_subscription / cancel_subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_subscription_modifies_first_item_quantity(
    provider,
    mock_stripe,
):
    mock_stripe.Subscription.retrieve.return_value = {
        "items": {"data": [{"id": "si_abc"}]},
    }

    await provider.update_subscription(
        "sub_123",
        plan_code="basic",
        billing_cycle="monthly",
        seats=7,
    )

    mock_stripe.Subscription.retrieve.assert_called_once_with("sub_123")
    modify_kwargs = mock_stripe.Subscription.modify.call_args
    assert modify_kwargs.args == ("sub_123",)
    items = modify_kwargs.kwargs["items"]
    assert items == [
        {
            "id": "si_abc",
            "price": "price_basic_monthly_fake",
            "quantity": 7,
        },
    ]


@pytest.mark.asyncio
async def test_cancel_subscription_sets_cancel_at_period_end(
    provider,
    mock_stripe,
):
    await provider.cancel_subscription("sub_999")
    mock_stripe.Subscription.modify.assert_called_once_with(
        "sub_999",
        cancel_at_period_end=True,
    )


# ---------------------------------------------------------------------------
# Price map loading
# ---------------------------------------------------------------------------


def test_provider_raises_if_price_map_missing(mock_stripe, tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(StripePriceMapMissing):
        StripeProvider("sk_test", "whsec", price_map_path=missing)


def test_provider_raises_on_placeholder_price_id(mock_stripe, tmp_path):
    """The default committed `stripe_price_map.yaml` ships with
    `REPLACE_ME_…` placeholders so the failure is loud before
    Checkout is ever attempted."""
    path = tmp_path / "prices.yaml"
    path.write_text(
        yaml.safe_dump({"basic": {"monthly": "REPLACE_ME_basic_monthly"}}),
        encoding="utf-8",
    )
    provider = StripeProvider("sk_test", "whsec", price_map_path=path)
    with pytest.raises(StripePriceMapMissing):
        provider._resolve_price_id("basic", "monthly")


# ---------------------------------------------------------------------------
# Seed script
# ---------------------------------------------------------------------------


def _build_seed_stripe_mock() -> MagicMock:
    """A `MagicMock` shaped like the Stripe SDK pieces the seed touches.

    Empty `auto_paging_iter` simulates a fresh Stripe account; subsequent
    calls mutate the mock so the iterator yields the seeded objects.
    """
    sdk = MagicMock(name="stripe-seed")
    sdk.api_key = "sk_test_seed"
    # `Product.list(...).auto_paging_iter()` and `Price.list(...).auto_paging_iter()`
    sdk._products: list[dict] = []
    sdk._prices: list[dict] = []

    def product_list(**_kwargs):
        listing = MagicMock()
        listing.auto_paging_iter.return_value = iter(list(sdk._products))
        return listing

    def price_list(product=None, **_kwargs):
        listing = MagicMock()
        listing.auto_paging_iter.return_value = iter(
            [p for p in sdk._prices if p.get("product") == product]
        )
        return listing

    def product_create(**kwargs):
        new = {
            "id": f"prod_{kwargs['metadata']['plan_code']}",
            "metadata": dict(kwargs["metadata"]),
        }
        sdk._products.append(new)
        return new

    def price_create(**kwargs):
        new = {
            "id": (
                f"price_{kwargs['metadata']['plan_code']}_{kwargs['metadata']['billing_cycle']}"
            ),
            "product": kwargs["product"],
            "metadata": dict(kwargs["metadata"]),
        }
        sdk._prices.append(new)
        return new

    sdk.Product.list.side_effect = product_list
    sdk.Product.create.side_effect = product_create
    sdk.Price.list.side_effect = price_list
    sdk.Price.create.side_effect = price_create
    return sdk


def test_seed_script_is_idempotent(tmp_path):
    from src.app.scripts import seed_stripe_catalog

    sdk = _build_seed_stripe_mock()
    out = tmp_path / "out.yaml"

    first_map = seed_stripe_catalog.run(stripe_sdk=sdk, output_path=out)
    create_calls_after_first = sdk.Product.create.call_count + sdk.Price.create.call_count

    second_map = seed_stripe_catalog.run(stripe_sdk=sdk, output_path=out)
    create_calls_after_second = sdk.Product.create.call_count + sdk.Price.create.call_count

    assert first_map == second_map
    # No new creates on the second run — every object was found via
    # metadata match.
    assert create_calls_after_second == create_calls_after_first


def test_seed_script_writes_yaml_loadable_in_a_fresh_process(tmp_path):
    """The persisted map must round-trip via PyYAML into the same dict
    the script returned in memory."""
    from src.app.scripts import seed_stripe_catalog

    sdk = _build_seed_stripe_mock()
    out = tmp_path / "out.yaml"

    in_memory = seed_stripe_catalog.run(stripe_sdk=sdk, output_path=out)

    with out.open("r", encoding="utf-8") as f:
        on_disk = yaml.safe_load(f)
    assert on_disk == in_memory
