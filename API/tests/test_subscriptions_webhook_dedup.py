"""Tests for the Step 13.a Stripe webhook frame.

Covers signature verification, dedup ledger semantics, and handler-
exception persistence — the dispatch table is empty in 13.a so
"handler success" means "no_op handler returned None".

The Stripe provider is overridden via `app.dependency_overrides` so
every test runs against an in-memory `AsyncMock` that returns
pre-built event dicts. The webhook endpoint is unauthenticated, so
no JWT setup is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.models import StripeWebhookEvent
from src.app.core.subscriptions.providers.stripe_provider import (
    InvalidWebhookSignature,
)
from src.app.core.subscriptions.webhooks import router as webhook_router_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(event_id: str, event_type: str = "test.event") -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": {}},
    }


@pytest.fixture
def mock_provider():
    """Provider whose `verify_webhook` is an `AsyncMock`. Each test
    sets `return_value` or `side_effect` as needed before posting."""
    provider = MagicMock(name="provider")
    provider.verify_webhook = AsyncMock()
    return provider


@pytest.fixture
def override_provider(layered_client, mock_provider):
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: mock_provider
    get_payment_provider.cache_clear()
    try:
        yield mock_provider
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_signature_returns_400_and_no_row(
    layered_client,
    override_provider,
):
    from tests.conftest import TestSession

    override_provider.verify_webhook.side_effect = InvalidWebhookSignature("bad sig")

    resp = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_xx"}',
        headers={"stripe-signature": "t=1,v1=garbage"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_signature"

    # No ledger row written on signature failure.
    async with TestSession() as session:
        count = (await session.execute(select(StripeWebhookEvent))).all()
    assert count == []


# ---------------------------------------------------------------------------
# Happy path — fresh event becomes a processed row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_event_is_persisted_and_marked_processed(
    layered_client,
    override_provider,
):
    from tests.conftest import TestSession

    override_provider.verify_webhook.return_value = _make_event(
        "evt_first",
        "checkout.session.completed",
    )

    resp = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_first"}',
        headers={"stripe-signature": "t=1,v1=ok"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["received"] is True
    assert body["duplicate"] is False

    async with TestSession() as session:
        row = (
            await session.execute(
                select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == "evt_first")
            )
        ).scalar_one()
        assert row.event_type == "checkout.session.completed"
        assert row.processed_at is not None
        assert row.error is None
        assert row.payload["type"] == "checkout.session.completed"


# ---------------------------------------------------------------------------
# Replay — same event ID is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_is_idempotent_single_row(
    layered_client,
    override_provider,
):
    from tests.conftest import TestSession

    override_provider.verify_webhook.return_value = _make_event(
        "evt_replay",
        "invoice.paid",
    )

    first = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_replay"}',
        headers={"stripe-signature": "t=1,v1=ok"},
    )
    second = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_replay"}',
        headers={"stripe-signature": "t=1,v1=ok"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True

    async with TestSession() as session:
        rows = (
            (
                await session.execute(
                    select(StripeWebhookEvent).where(
                        StripeWebhookEvent.stripe_event_id == "evt_replay"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Handler exception — 500, error persisted, processed_at stays NULL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_exception_persists_error_and_returns_500(
    layered_client,
    override_provider,
    monkeypatch,
):
    """If a registered handler raises, the row's `error` is filled,
    `processed_at` stays NULL so Stripe's retry re-runs it, and the
    response is 500."""
    from tests.conftest import TestSession

    async def boom(db, event):  # noqa: ARG001
        raise RuntimeError("kaboom")

    # Register `boom` as the handler for our event type. Patch the
    # module-level dispatch table so the test is hermetic — restore
    # is via monkeypatch.
    monkeypatch.setitem(
        webhook_router_module._HANDLERS,
        "test.boom",
        boom,
    )

    override_provider.verify_webhook.return_value = _make_event(
        "evt_boom",
        "test.boom",
    )

    resp = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_boom"}',
        headers={"stripe-signature": "t=1,v1=ok"},
    )
    assert resp.status_code == 500, resp.text

    async with TestSession() as session:
        row = (
            await session.execute(
                select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == "evt_boom")
            )
        ).scalar_one()
        assert row.processed_at is None
        assert row.error is not None
        assert "kaboom" in row.error


# ---------------------------------------------------------------------------
# Missing event ID — 400, no row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_event_id_returns_400(
    layered_client,
    override_provider,
):
    from tests.conftest import TestSession

    override_provider.verify_webhook.return_value = {
        "type": "test.event",
        # `id` deliberately absent
    }

    resp = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=ok"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "missing_event_id"

    async with TestSession() as session:
        count = (await session.execute(select(StripeWebhookEvent))).all()
    assert count == []


# ---------------------------------------------------------------------------
# 503 when provider not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_unavailable_returns_503(layered_client):
    """No `STRIPE_SECRET_KEY` → provider dep returns None → 503."""
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: None
    get_payment_provider.cache_clear()
    try:
        resp = await layered_client.post(
            "/api/v1/webhooks/stripe",
            content=b'{"id":"evt_x"}',
            headers={"stripe-signature": "t=1,v1=ok"},
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["error"] == "payment_provider_unavailable"
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()
