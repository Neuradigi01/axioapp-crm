"""Property DAL — smoke tests covering the pure-CRUD surface.

Verifies that every DAL helper in
`packs/real_estate/modules/property/data_access.py` round-trips as
expected against a fresh test schema, and that the DB-level
invariants declared in the migration (FK cascade + partial unique
index for featured images) fire correctly.

No service, no router — this is the DAL alone.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from src.app.packs.real_estate.modules.property import data_access as dal
from src.app.packs.real_estate.modules.property.models import Property, PropertyImage


def _make_property(
    org_id: uuid.UUID,
    *,
    title: str = "Sea-facing 3 BHK",
    slug: str | None = None,
    status: str = "draft",
    property_type: str = "apartment",
    category: str = "residential_sale",
    city: str = "Mumbai",
    price: str | None = "25000000",
) -> Property:
    return Property(
        org_id=org_id,
        owner_id=uuid.uuid4(),
        title=title,
        slug=slug or f"prop-{uuid.uuid4().hex[:8]}",
        property_type=property_type,
        category=category,
        price=price,
        currency="INR",
        city=city,
        state="Maharashtra",
        country="India",
        pincode="400001",
        bedrooms=3,
        bathrooms=2,
        area_value="1450",
        area_unit="sqft",
        amenities=["Parking", "Gym", "Pool"],
        status=status,
    )


@pytest.mark.asyncio
async def test_insert_and_get_property_round_trips(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    prop = _make_property(org_id, title="Sea-facing 3 BHK")

    dal.insert_property(test_db, prop)
    await test_db.commit()
    await test_db.refresh(prop)

    fetched = await dal.get_property_by_id(test_db, property_id=prop.id)
    assert fetched is not None
    assert fetched.id == prop.id
    assert fetched.title == "Sea-facing 3 BHK"
    assert fetched.status == "draft"
    assert fetched.amenities == ["Parking", "Gym", "Pool"]
    assert fetched.currency == "INR"


@pytest.mark.asyncio
async def test_get_property_by_slug_scopes_to_org(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    prop = _make_property(org_id, slug="sea-facing-3-bhk")
    dal.insert_property(test_db, prop)
    await test_db.commit()

    found = await dal.get_property_by_slug(test_db, org_id=org_id, slug="sea-facing-3-bhk")
    assert found is not None
    assert found.id == prop.id

    miss = await dal.get_property_by_slug(test_db, org_id=uuid.uuid4(), slug="sea-facing-3-bhk")
    assert miss is None


@pytest.mark.asyncio
async def test_list_properties_paginates_and_counts(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    for i in range(5):
        dal.insert_property(
            test_db,
            _make_property(org_id, title=f"Listing {i}", status="published"),
        )
    await test_db.commit()

    rows, total = await dal.list_properties(test_db, statuses=["published"], page=1, size=3)
    assert total == 5
    assert len(rows) == 3

    rows_p2, _ = await dal.list_properties(test_db, statuses=["published"], page=2, size=3)
    assert len(rows_p2) == 2


@pytest.mark.asyncio
async def test_count_properties_by_status_returns_histogram(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    dal.insert_property(test_db, _make_property(org_id, status="draft"))
    dal.insert_property(test_db, _make_property(org_id, status="draft"))
    dal.insert_property(test_db, _make_property(org_id, status="published"))
    await test_db.commit()

    counts = await dal.count_properties_by_status(test_db, org_id=org_id)
    assert counts.get("draft") == 2
    assert counts.get("published") == 1


@pytest.mark.asyncio
async def test_delete_property_cascades_to_images(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    prop = _make_property(org_id)
    dal.insert_property(test_db, prop)
    await test_db.commit()
    await test_db.refresh(prop)

    img = PropertyImage(
        org_id=org_id,
        property_id=prop.id,
        image_path=f"{org_id}/property/{prop.id}/1.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
        display_order=0,
        is_featured=True,
    )
    dal.insert_property_image(test_db, img)
    await test_db.commit()
    await test_db.refresh(img)

    images_before = await dal.list_property_images(test_db, property_id=prop.id)
    assert len(images_before) == 1

    await dal.delete_property_row(test_db, prop)
    await test_db.commit()

    images_after = await dal.list_property_images(test_db, property_id=prop.id)
    assert images_after == []


@pytest.mark.asyncio
async def test_only_one_featured_image_per_property(test_db, seeded_admin):
    """The partial UNIQUE index `uq_rp_property_images_featured`
    guarantees at-most-one `is_featured=true` per property. Trying to
    insert a second must fail with IntegrityError."""
    org_id = seeded_admin["org"].id
    prop = _make_property(org_id)
    dal.insert_property(test_db, prop)
    await test_db.commit()
    await test_db.refresh(prop)

    img_a = PropertyImage(
        org_id=org_id,
        property_id=prop.id,
        image_path="a.jpg",
        display_order=0,
        is_featured=True,
    )
    dal.insert_property_image(test_db, img_a)
    await test_db.commit()

    img_b = PropertyImage(
        org_id=org_id,
        property_id=prop.id,
        image_path="b.jpg",
        display_order=1,
        is_featured=True,
    )
    dal.insert_property_image(test_db, img_b)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_slug_is_unique_per_org(test_db, seeded_admin):
    """`uq_rp_properties_org_slug` prevents two rows with the same
    (org_id, slug) — the service uses this as a collision check
    before insert."""
    org_id = seeded_admin["org"].id
    first = _make_property(org_id, slug="hilltop-villa")
    dal.insert_property(test_db, first)
    await test_db.commit()

    second = _make_property(org_id, slug="hilltop-villa")
    dal.insert_property(test_db, second)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()
