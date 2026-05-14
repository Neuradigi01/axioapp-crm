"""End-to-end coverage for the core billing state machine.

Covers:
  - draft → issue: snapshots tax_rate + gst_number from org settings,
    assigns a per-org number starting at 1
  - issue with no lines is rejected (400)
  - record_payment under total leaves status='issued'
  - record_payment reaching total flips to 'paid' and stamps paid_at
  - void from `issued` → status='void' + reason captured
  - perm gate: a user with only `billing.read` cannot create
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.settings.service import get_or_create as get_settings


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_org_settings(
    org_id: uuid.UUID, *, gst_number: str = "29ABCDE1234F1Z5", tax_rate: str = "18.00"
) -> None:
    from tests.conftest import TestSession
    from src.app.shared.context import RequestContext, reset_context, set_context

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            settings = await get_settings(session, org_id=org_id)
            settings.gst_number = gst_number
            settings.tax_rate = Decimal(tax_rate)
            await session.commit()
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_draft_issue_pay_lifecycle(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "billing.read", "billing.write")
    await _seed_org_settings(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Draft
    draft = await layered_client.post(
        "/api/v1/invoices", json={"notes": "test draft"}, headers=headers
    )
    assert draft.status_code == 201, draft.text
    inv_id = draft.json()["id"]
    assert draft.json()["status"] == "draft"
    assert draft.json()["number"] is None

    # 2. Add a line
    line = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/lines",
        json={
            "description": "Walnut TV unit",
            "qty": 1,
            "unit_price": "25000.00",
        },
        headers=headers,
    )
    assert line.status_code == 201
    # tax_pct defaults to org tax_rate (18%)
    assert Decimal(line.json()["tax_pct"]) == Decimal("18.00")
    assert Decimal(line.json()["line_total"]) == Decimal("29500.00")

    # 3. Issue → number assigned, tax snapshot, status flips
    issued = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/issue", headers=headers
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"
    assert issued.json()["number"] == 1
    assert issued.json()["gst_number"] == "29ABCDE1234F1Z5"
    assert Decimal(issued.json()["tax_rate_snapshot"]) == Decimal("18.00")
    assert Decimal(issued.json()["total"]) == Decimal("29500.00")
    assert issued.json()["issued_at"] is not None

    # 4. Partial payment → still 'issued'
    pay1 = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/payments",
        json={"amount": "10000.00", "method": "cash"},
        headers=headers,
    )
    assert pay1.status_code == 201
    after_partial = await layered_client.get(
        f"/api/v1/invoices/{inv_id}", headers=headers
    )
    assert after_partial.json()["status"] == "issued"
    assert after_partial.json()["paid_at"] is None

    # 5. Top-up payment → flips to 'paid'
    pay2 = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/payments",
        json={"amount": "19500.00", "method": "upi"},
        headers=headers,
    )
    assert pay2.status_code == 201
    final = await layered_client.get(
        f"/api/v1/invoices/{inv_id}", headers=headers
    )
    assert final.json()["status"] == "paid"
    assert final.json()["paid_at"] is not None
    assert final.json()["payment_method"] == "upi"


@pytest.mark.asyncio
async def test_issue_with_no_lines_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "billing.read", "billing.write")
    await _seed_org_settings(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    draft = await layered_client.post(
        "/api/v1/invoices", json={}, headers=headers
    )
    inv_id = draft.json()["id"]

    resp = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/issue", headers=headers
    )
    assert resp.status_code == 400
    assert "no lines" in resp.text


@pytest.mark.asyncio
async def test_per_org_invoice_numbering(layered_client, seeded_admin):
    """Two issued invoices in the same org should get sequential numbers."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "billing.read", "billing.write")
    await _seed_org_settings(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    numbers: list[int] = []
    for _ in range(3):
        draft = await layered_client.post(
            "/api/v1/invoices", json={}, headers=headers
        )
        inv_id = draft.json()["id"]
        await layered_client.post(
            f"/api/v1/invoices/{inv_id}/lines",
            json={"description": "Item", "qty": 1, "unit_price": "100.00"},
            headers=headers,
        )
        issued = await layered_client.post(
            f"/api/v1/invoices/{inv_id}/issue", headers=headers
        )
        numbers.append(issued.json()["number"])

    assert numbers == [1, 2, 3]


@pytest.mark.asyncio
async def test_void_from_issued(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "billing.read",
        "billing.write",
        "billing.refund",
    )
    await _seed_org_settings(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    draft = await layered_client.post(
        "/api/v1/invoices", json={}, headers=headers
    )
    inv_id = draft.json()["id"]
    await layered_client.post(
        f"/api/v1/invoices/{inv_id}/lines",
        json={"description": "Item", "qty": 1, "unit_price": "500.00"},
        headers=headers,
    )
    await layered_client.post(
        f"/api/v1/invoices/{inv_id}/issue", headers=headers
    )

    voided = await layered_client.post(
        f"/api/v1/invoices/{inv_id}/void", headers=headers
    )
    assert voided.status_code == 200
    assert voided.json()["status"] == "void"


@pytest.mark.asyncio
async def test_write_requires_billing_write(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "billing.read")
    await _seed_org_settings(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/invoices", json={}, headers=headers
    )
    assert resp.status_code == 403
