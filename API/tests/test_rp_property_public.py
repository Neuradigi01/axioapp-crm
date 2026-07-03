"""Public property endpoints — Fernet token round-trip + isolation.

Exercises `service.get_public_property` and `service.list_public_properties`
directly. The router thin-wraps these and translates ``None`` to 404;
covered separately at the router-integration layer once the frontend
lands (Step 9).
"""

from __future__ import annotations

import io
import os
import uuid

import pytest
from PIL import Image

from src.app.packs.real_estate.modules.property import data_access as dal
from src.app.packs.real_estate.modules.property import link_token
from src.app.packs.real_estate.modules.property.constants import (
    PropertyCategory,
    PropertyType,
)
from src.app.packs.real_estate.modules.property.schemas import PropertyCreate
from src.app.packs.real_estate.modules.property.service import (
    archive_property,
    create_property,
    generate_public_link,
    get_public_property,
    list_public_properties,
    publish_property,
    unpublish_property,
    upload_property_images,
)


# A stable Fernet key just for tests — never leaves the test suite.
_TEST_KEY = "MlQ8eZQ-Avj_QejfxzPts2JVuQ3CU1sGiDltuoDOU6Q="


@pytest.fixture(autouse=True)
def _property_link_key(monkeypatch):
    """Set the Fernet key + reset the lazy cache so every test starts
    from a known-good state."""
    monkeypatch.setenv("PROPERTY_LINK_ENCRYPTION_KEY", _TEST_KEY)
    import config

    monkeypatch.setattr(config, "PROPERTY_LINK_ENCRYPTION_KEY", _TEST_KEY)
    link_token.reset_cache()
    yield
    link_token.reset_cache()


@pytest.fixture(autouse=True)
def _patch_storage(tmp_path, monkeypatch):
    from src.app.shared.storage import get_storage
    from src.app.shared.storage.local import LocalStorage

    get_storage.cache_clear()
    monkeypatch.setattr(
        "src.app.packs.real_estate.modules.property.service.get_storage",
        lambda: LocalStorage(root=str(tmp_path)),
    )
    yield tmp_path
    get_storage.cache_clear()


def _jpeg() -> bytes:
    img = Image.new("RGB", (80, 60), (150, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def _published_property(db, seeded_admin):
    p = await create_property(
        db,
        org_id=seeded_admin["org"].id,
        actor_user_id=uuid.uuid4(),
        payload=PropertyCreate(
            title="Sea-facing 3 BHK",
            property_type=PropertyType.apartment,
            category=PropertyCategory.residential_sale,
            description="Spacious flat with sea view, close to schools and metro.",
            city="Mumbai",
        ),
    )
    await upload_property_images(
        db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        files=[("cover.jpg", _jpeg(), "image/jpeg")],
    )
    await publish_property(db, org_id=seeded_admin["org"].id, property_id=p.id)
    return p


@pytest.mark.asyncio
async def test_token_round_trip(test_db, seeded_admin):
    p = await _published_property(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        host="https://example.com",
    )
    decoded = link_token.decode_property_token(link.token)
    assert decoded == (p.id, seeded_admin["org"].id)
    assert link.url == f"https://example.com/property/{link.token}"


@pytest.mark.asyncio
async def test_public_fetch_returns_detail(test_db, seeded_admin):
    p = await _published_property(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        host="https://example.com",
    )
    detail = await get_public_property(test_db, token=link.token)
    assert detail is not None
    assert detail.title == "Sea-facing 3 BHK"
    assert detail.city == "Mumbai"
    assert len(detail.images) == 1
    assert detail.featured_image_url is not None


@pytest.mark.asyncio
async def test_tampered_token_returns_none(test_db, seeded_admin):
    p = await _published_property(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        host="https://example.com",
    )
    # Flip one character deep in the ciphertext (avoid the trailing pad).
    tampered = link.token[:-3] + ("A" if link.token[-3] != "A" else "B") + link.token[-2:]
    detail = await get_public_property(test_db, token=tampered)
    assert detail is None


@pytest.mark.asyncio
async def test_unpublished_property_returns_none(test_db, seeded_admin):
    p = await _published_property(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        host="https://example.com",
    )
    await unpublish_property(test_db, org_id=seeded_admin["org"].id, property_id=p.id)
    detail = await get_public_property(test_db, token=link.token)
    assert detail is None


@pytest.mark.asyncio
async def test_archived_property_returns_none(test_db, seeded_admin):
    p = await _published_property(test_db, seeded_admin)
    link = await generate_public_link(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=p.id,
        host="https://example.com",
    )
    await unpublish_property(test_db, org_id=seeded_admin["org"].id, property_id=p.id)
    await archive_property(test_db, org_id=seeded_admin["org"].id, property_id=p.id)
    detail = await get_public_property(test_db, token=link.token)
    assert detail is None


@pytest.mark.asyncio
async def test_list_returns_only_published_for_org(test_db, seeded_admin):
    p1 = await _published_property(test_db, seeded_admin)  # published
    p2 = await create_property(
        test_db,
        org_id=seeded_admin["org"].id,
        actor_user_id=uuid.uuid4(),
        payload=PropertyCreate(
            title="Draft only",
            property_type=PropertyType.villa,
            category=PropertyCategory.residential_sale,
        ),
    )  # stays draft
    cards = await list_public_properties(test_db, org_id=seeded_admin["org"].id)
    titles = {c.title for c in cards}
    assert "Sea-facing 3 BHK" in titles
    assert "Draft only" not in titles


@pytest.mark.asyncio
async def test_list_wrong_org_is_empty(test_db, seeded_admin):
    await _published_property(test_db, seeded_admin)
    cards = await list_public_properties(test_db, org_id=uuid.uuid4())
    assert cards == []


@pytest.mark.asyncio
async def test_generate_link_rejects_non_published(test_db, seeded_admin):
    from fastapi import HTTPException

    p = await create_property(
        test_db,
        org_id=seeded_admin["org"].id,
        actor_user_id=uuid.uuid4(),
        payload=PropertyCreate(
            title="Not yet published",
            property_type=PropertyType.villa,
            category=PropertyCategory.residential_sale,
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await generate_public_link(
            test_db,
            org_id=seeded_admin["org"].id,
            property_id=p.id,
            host="https://example.com",
        )
    assert exc.value.status_code == 409
