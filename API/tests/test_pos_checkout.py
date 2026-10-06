"""Coverage for `POST /api/v1/pos/checkout`.

Asserts the single-call POS flow does everything in one transaction:
  - contact auto-create by phone (and reuse on second checkout)
  - invoice created, lines pushed, issued (number assigned), payment
    recorded → status='paid'
  - tax computed from org_settings.tax_rate (not hardcoded)
  - inventory decremented for catalog-linked lines
  - PDF endpoint returns binary PDF content
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.catalog.models import CatalogItem
from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.settings.service import get_or_create as get_settings
from src.app.packs.furniture.modules.inventory.models import (
    InventoryItem,
    Warehouse,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.usefixtures("furniture_org")


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
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_org(org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Set up org settings, a default warehouse, a catalog item + an
    inventory row with 10 units in stock."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            settings = await get_settings(session, org_id=org_id)
            settings.gst_number = "29ABCDE1234F1Z5"
            settings.tax_rate = Decimal("18.00")

            warehouse = Warehouse(org_id=org_id, name="Main", is_default=True)
            session.add(warehouse)
            await session.flush()

            catalog = CatalogItem(
                org_id=org_id,
                sku="POS-TEST-1",
                name="Smoke chair",
                category="seating",
                price=Decimal("1000.00"),
                custom_data={},
                is_active=True,
            )
            session.add(catalog)
            await session.flush()

            inv = InventoryItem(
                org_id=org_id,
                catalog_item_id=catalog.id,
                warehouse_id=warehouse.id,
                sku="POS-TEST-1",
                qty_on_hand=10,
                reorder_level=2,
            )
            session.add(inv)
            await session.commit()
            return {
                "warehouse_id": warehouse.id,
                "catalog_id": catalog.id,
                "inventory_id": inv.id,
            }
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_pos_checkout_happy_path(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "billing.read",
        "billing.write",
        "pos.use",
        "inventory.dispatch",
    )
    ids = await _seed_org(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/pos/checkout",
        json={
            "contact_phone": "+919876543210",
            "contact_name": "POS Tester",
            "lines": [
                {
                    "catalog_item_id": str(ids["catalog_id"]),
                    "description": "Smoke chair",
                    "qty": 3,
                    "unit_price": "1000.00",
                },
            ],
            "payment_method": "cash",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    inv = body["invoice"]

    # Invoice issued + paid in one shot
    assert inv["status"] == "paid"
    assert inv["number"] == 1
    assert inv["gst_number"] == "29ABCDE1234F1Z5"
    # 3 × 1000 = 3000 subtotal + 18% tax = 3540
    assert Decimal(inv["subtotal"]) == Decimal("3000.00")
    assert Decimal(inv["tax_amount"]) == Decimal("540.00")
    assert Decimal(inv["total"]) == Decimal("3540.00")
    assert inv["payment_method"] == "cash"

    # PDF URL points at the core endpoint
    assert body["pdf_url"].endswith(f"/api/v1/invoices/{inv['id']}/pdf")

    # Inventory decremented from 10 → 7
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            inv_row = (
                await session.execute(
                    select(InventoryItem).where(InventoryItem.id == ids["inventory_id"])
                )
            ).scalar_one()
            assert inv_row.qty_on_hand == 7

            # Contact auto-created with the supplied phone
            contact = (
                await session.execute(
                    select(Contact).where(
                        Contact.org_id == org.id,
                        Contact.phone == "+919876543210",
                    )
                )
            ).scalar_one()
            assert contact.full_name == "POS Tester"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_pos_reuses_existing_contact(layered_client, seeded_admin):
    """Second checkout for the same phone reuses the existing contact."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "billing.read",
        "billing.write",
        "pos.use",
        "inventory.dispatch",
    )
    ids = await _seed_org(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(2):
        resp = await layered_client.post(
            "/api/v1/pos/checkout",
            json={
                "contact_phone": "+919999999999",
                "contact_name": "Repeat Customer",
                "lines": [
                    {
                        "catalog_item_id": str(ids["catalog_id"]),
                        "description": "Smoke chair",
                        "qty": 1,
                        "unit_price": "1000.00",
                    },
                ],
                "payment_method": "card",
            },
            headers=headers,
        )
        assert resp.status_code == 201

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            contacts = (
                (
                    await session.execute(
                        select(Contact).where(
                            Contact.org_id == org.id,
                            Contact.phone == "+919999999999",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(contacts) == 1
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_pos_pdf_endpoint_returns_pdf(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "billing.read",
        "billing.write",
        "pos.use",
        "inventory.dispatch",
    )
    ids = await _seed_org(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    checkout = await layered_client.post(
        "/api/v1/pos/checkout",
        json={
            "contact_phone": "+919111111111",
            "lines": [
                {
                    "catalog_item_id": str(ids["catalog_id"]),
                    "description": "Smoke chair",
                    "qty": 1,
                    "unit_price": "1000.00",
                },
            ],
            "payment_method": "cash",
        },
        headers=headers,
    )
    inv_id = checkout.json()["invoice"]["id"]

    pdf = await layered_client.get(f"/api/v1/invoices/{inv_id}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    # PDF files start with the %PDF magic bytes
    assert pdf.content[:4] == b"%PDF"
