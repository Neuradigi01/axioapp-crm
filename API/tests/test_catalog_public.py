"""Public catalog endpoints — Fernet token round-trip + isolation.

Exercises ``service.get_public_item`` and ``service.list_public_items``
directly, plus the state-machine gates on ``generate_public_link``.
Mirrors ``test_rp_property_public.py`` — same shape, adapted to
catalog's slightly leaner state machine (no ``sold`` terminal).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.app.core.catalog import data_access as dal
from src.app.core.catalog import link_token
from src.app.core.catalog.models import CatalogItem
from src.app.core.catalog.schemas import CatalogItemCreate
from src.app.core.catalog.service import (
    archive_item,
    create_item,
    generate_public_link,
    get_public_item,
    list_public_items,
    publish_item,
    unpublish_item,
)


# A stable Fernet key just for tests — never leaves the test suite.
_TEST_KEY = "MlQ8eZQ-Avj_QejfxzPts2JVuQ3CU1sGiDltuoDOU6Q="


@pytest.fixture(autouse=True)
def _catalog_link_key(monkeypatch):
    """Set the Fernet key + reset the lazy cache so every test starts
    from a known-good state."""
    monkeypatch.setenv("CATALOG_LINK_ENCRYPTION_KEY", _TEST_KEY)
    import config

    monkeypatch.setattr(config, "CATALOG_LINK_ENCRYPTION_KEY", _TEST_KEY)
    link_token.reset_cache()
    yield
    link_token.reset_cache()


async def _published_item(db, seeded_admin) -> CatalogItem:
    item = await create_item(
        db,
        org_id=seeded_admin["org"].id,
        payload=CatalogItemCreate(
            sku=f"TEST-{uuid.uuid4().hex[:8].upper()}",
            name="Comfy Sofa",
            description="Roomy 3-seater with washable covers.",
            price=Decimal("24999"),
            currency="INR",
        ),
    )
    # Publishing requires at least one image — the state machine
    # rejects a photoless publish otherwise. Set a placeholder URL
    # directly on the ORM row so we skip the multipart-upload path.
    item.image_url = "/files/test/placeholder.jpg"
    await db.commit()
    await db.refresh(item)
    await publish_item(db, item_id=item.id)
    return item


@pytest.mark.asyncio
async def test_token_round_trip(test_db, seeded_admin):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    decoded = link_token.decode_catalog_token(link.token)
    assert decoded == (item.id, seeded_admin["org"].id)
    assert link.url == f"https://example.com/product/{link.token}"


@pytest.mark.asyncio
async def test_public_fetch_returns_detail(test_db, seeded_admin):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    detail = await get_public_item(test_db, token=link.token)
    assert detail is not None
    assert detail.name == "Comfy Sofa"
    assert detail.image_url == "/files/test/placeholder.jpg"


@pytest.mark.asyncio
async def test_tampered_token_returns_none(test_db, seeded_admin):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    # Flip one character deep in the ciphertext (avoid the trailing pad).
    tampered = link.token[:-3] + ("A" if link.token[-3] != "A" else "B") + link.token[-2:]
    detail = await get_public_item(test_db, token=tampered)
    assert detail is None


@pytest.mark.asyncio
async def test_unpublished_item_returns_none(test_db, seeded_admin):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    await unpublish_item(test_db, item_id=item.id)
    detail = await get_public_item(test_db, token=link.token)
    assert detail is None


@pytest.mark.asyncio
async def test_archived_item_returns_none(test_db, seeded_admin):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    await unpublish_item(test_db, item_id=item.id)
    await archive_item(test_db, item_id=item.id)
    detail = await get_public_item(test_db, token=link.token)
    assert detail is None


@pytest.mark.asyncio
async def test_list_returns_only_published_for_org(test_db, seeded_admin):
    p1 = await _published_item(test_db, seeded_admin)
    # A separate draft item — must NOT appear on the public grid.
    p2 = await create_item(
        test_db,
        org_id=seeded_admin["org"].id,
        payload=CatalogItemCreate(
            sku=f"DRAFT-{uuid.uuid4().hex[:8].upper()}",
            name="Draft Chair",
            price=Decimal("1299"),
            currency="INR",
        ),
    )
    assert p2.status == "draft"
    cards = await list_public_items(test_db, org_id=seeded_admin["org"].id)
    names = {c.name for c in cards}
    assert "Comfy Sofa" in names
    assert "Draft Chair" not in names


@pytest.mark.asyncio
async def test_list_wrong_org_is_empty(test_db, seeded_admin):
    await _published_item(test_db, seeded_admin)
    cards = await list_public_items(test_db, org_id=uuid.uuid4())
    assert cards == []


@pytest.mark.asyncio
async def test_generate_link_rejects_non_published(test_db, seeded_admin):
    from fastapi import HTTPException

    item = await create_item(
        test_db,
        org_id=seeded_admin["org"].id,
        payload=CatalogItemCreate(
            sku=f"NP-{uuid.uuid4().hex[:8].upper()}",
            name="Not yet published",
            price=Decimal("1000"),
            currency="INR",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await generate_public_link(
            test_db,
            org_id=seeded_admin["org"].id,
            item_id=item.id,
            host="https://example.com",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_requires_image(test_db, seeded_admin):
    from fastapi import HTTPException

    item = await create_item(
        test_db,
        org_id=seeded_admin["org"].id,
        payload=CatalogItemCreate(
            sku=f"NI-{uuid.uuid4().hex[:8].upper()}",
            name="No image",
            price=Decimal("500"),
            currency="INR",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await publish_item(test_db, item_id=item.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_key_rotation_invalidates_old_tokens(test_db, seeded_admin, monkeypatch):
    item = await _published_item(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        item_id=item.id,
        host="https://example.com",
    )
    # Rotate the key — every existing token must now fail to decrypt.
    new_key = "F1XSPjRb04FIBFEsBcpsZ5wpwqQP0nfxxK-tZa5T3-A="
    import config

    monkeypatch.setattr(config, "CATALOG_LINK_ENCRYPTION_KEY", new_key)
    link_token.reset_cache()
    detail = await get_public_item(test_db, token=link.token)
    assert detail is None


@pytest.mark.asyncio
async def test_list_published_items_dal_direct(test_db, seeded_admin):
    """Guard the DAL loader directly — the public grid depends on
    ``published_at DESC NULLS LAST`` for freshest-first ordering."""
    await _published_item(test_db, seeded_admin)
    rows = await dal.list_published_items(test_db, org_id=seeded_admin["org"].id)
    assert all(r.status == "published" for r in rows)
    assert all(r.org_id == seeded_admin["org"].id for r in rows)
