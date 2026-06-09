"""Tests for `GET /api/v1/subscriptions/invoices` (Step 13.c).

Two scenarios:

  - Multiple invoices return in reverse-chrono order with all the
    fields the billing settings page consumes.
  - Cross-org isolation — a user in org A never sees org B's
    invoices, even when both orgs have rows in the same table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.app.core.subscriptions.models import (
    Subscription,
    SubscriptionInvoice,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _login(client, *, email, password, org_slug) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _login_seeded(client, seeded_admin) -> str:
    return await _login(
        client,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
        org_slug=seeded_admin["org"].slug,
    )


async def _insert_subscription(org_id: uuid.UUID) -> uuid.UUID:
    from tests.conftest import TestSession

    now = datetime.now(tz=timezone.utc)
    async with TestSession() as session:
        sub = Subscription(
            org_id=org_id,
            plan_code="basic",
            status="active",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            stripe_subscription_id=f"sub_{uuid.uuid4().hex[:10]}",
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _insert_invoice(
    org_id: uuid.UUID,
    sub_id: uuid.UUID,
    *,
    stripe_invoice_id: str,
    number: str,
    status: str = "paid",
    amount_due_cents: int = 6000,
    amount_paid_cents: int = 6000,
    created_at: datetime | None = None,
    paid_at: datetime | None = None,
) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        row = SubscriptionInvoice(
            org_id=org_id,
            subscription_id=sub_id,
            stripe_invoice_id=stripe_invoice_id,
            number=number,
            status=status,
            amount_due_cents=amount_due_cents,
            amount_paid_cents=amount_paid_cents,
            currency="USD",
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            hosted_invoice_url=f"https://invoice.stripe.com/{stripe_invoice_id}",
            pdf_url=f"https://pay.stripe.com/{stripe_invoice_id}.pdf",
            paid_at=paid_at,
        )
        if created_at is not None:
            # `created_at` defaults to `now()` server-side; tests that
            # care about ordering override it via raw assignment after
            # `add` but before commit.
            row.created_at = created_at
        session.add(row)
        await session.commit()


# ---------------------------------------------------------------------------
# Reverse-chrono listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoices_listed_in_reverse_chrono_order(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    sub_id = await _insert_subscription(org.id)

    now = datetime.now(tz=timezone.utc)
    # Insert oldest first so the test reads against the ordering, not
    # the insertion sequence.
    await _insert_invoice(
        org.id, sub_id,
        stripe_invoice_id="in_001",
        number="INV-001",
        created_at=now - timedelta(days=60),
        paid_at=now - timedelta(days=60),
    )
    await _insert_invoice(
        org.id, sub_id,
        stripe_invoice_id="in_002",
        number="INV-002",
        created_at=now - timedelta(days=30),
        paid_at=now - timedelta(days=30),
    )
    await _insert_invoice(
        org.id, sub_id,
        stripe_invoice_id="in_003",
        number="INV-003",
        created_at=now - timedelta(days=1),
        paid_at=now - timedelta(days=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.get(
        "/api/v1/subscriptions/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert [r["number"] for r in body] == ["INV-003", "INV-002", "INV-001"]
    first = body[0]
    assert first["status"] == "paid"
    assert first["amount_paid_cents"] == 6000
    assert first["hosted_invoice_url"].endswith("in_003")
    assert first["pdf_url"].endswith("in_003.pdf")


# ---------------------------------------------------------------------------
# Cross-org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_isolation(layered_client, seeded_admin):
    """A user in org A must never see org B's invoices, even when both
    orgs have invoice rows in the same `subscription_invoices` table."""
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    sub_a = await _insert_subscription(org_a.id)
    await _insert_invoice(
        org_a.id, sub_a,
        stripe_invoice_id="in_orga_1", number="A-001",
    )

    # Build a fresh org B with its own sub + invoice.
    org_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_b_id, name="Other Co",
                slug=f"other-{uuid.uuid4().hex[:6]}",
            )
        )
        await session.commit()
    sub_b = await _insert_subscription(org_b_id)
    await _insert_invoice(
        org_b_id, sub_b,
        stripe_invoice_id="in_orgb_1", number="B-001",
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.get(
        "/api/v1/subscriptions/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    numbers = {row["number"] for row in body}
    assert numbers == {"A-001"}
    assert "B-001" not in numbers


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_list_when_no_invoices(layered_client, seeded_admin):
    """An org with a subscription but no Stripe activity yet returns
    an empty list, not 404 — the billing page renders the empty
    state, not an error."""
    org = seeded_admin["org"]
    await _insert_subscription(org.id)

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.get(
        "/api/v1/subscriptions/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
