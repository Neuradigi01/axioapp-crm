"""Property service — CRUD + state machine + slug behavior.

Exercises `service.py` directly against a fresh `test_db` schema (no
HTTP layer). Auth, permissions and JSON serialization are tested at
the router integration layer once the frontend needs them; here the
scope is: does the business logic land the right rows and reject the
right transitions?
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from src.app.packs.real_estate.modules.property import data_access as dal
from src.app.packs.real_estate.modules.property.constants import (
    PropertyCategory,
    PropertyStatus,
    PropertyType,
)
from src.app.packs.real_estate.modules.property.models import PropertyImage
from src.app.packs.real_estate.modules.property.schemas import (
    PropertyCreate,
    PropertyListFilters,
    PropertyUpdate,
)
from src.app.packs.real_estate.modules.property.service import (
    archive_property,
    create_property,
    delete_property,
    get_property,
    list_properties,
    mark_sold,
    publish_property,
    unarchive_property,
    unpublish_property,
    update_property,
)


def _payload(**kw) -> PropertyCreate:
    base = dict(
        title="Sea-facing 3 BHK",
        property_type=PropertyType.apartment,
        category=PropertyCategory.residential_sale,
        city="Mumbai",
        price="25000000",
    )
    base.update(kw)
    return PropertyCreate(**base)


async def _add_image(db, *, org_id: uuid.UUID, property_id: uuid.UUID) -> None:
    img = PropertyImage(
        org_id=org_id,
        property_id=property_id,
        image_path=f"{org_id}/property/{property_id}/x.jpg",
        display_order=0,
        is_featured=True,
    )
    dal.insert_property_image(db, img)
    await db.commit()


@pytest.mark.asyncio
async def test_create_property_ok(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    actor = uuid.uuid4()
    p = await create_property(test_db, org_id=org_id, actor_user_id=actor, payload=_payload())
    assert p.id is not None
    assert p.status == PropertyStatus.draft.value
    assert p.slug.startswith("sea-facing-3-bhk")
    assert p.title == "Sea-facing 3 BHK"
    assert p.currency == "INR"


@pytest.mark.asyncio
async def test_publish_requires_image(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    with pytest.raises(HTTPException) as exc:
        await publish_property(test_db, org_id=org_id, property_id=p.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_publish_transitions_state_and_timestamps(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    await _add_image(test_db, org_id=org_id, property_id=p.id)
    pub = await publish_property(test_db, org_id=org_id, property_id=p.id)
    assert pub.status == PropertyStatus.published.value
    assert pub.published_at is not None


@pytest.mark.asyncio
async def test_update_regenerates_slug_on_title_change(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    original_slug = p.slug
    upd = await update_property(
        test_db,
        org_id=org_id,
        property_id=p.id,
        payload=PropertyUpdate(title="Hilltop Villa With Pool"),
    )
    assert upd.slug != original_slug
    assert upd.slug.startswith("hilltop-villa-with-pool")

    upd_again = await update_property(
        test_db,
        org_id=org_id,
        property_id=p.id,
        payload=PropertyUpdate(description="No title change"),
    )
    assert upd_again.slug == upd.slug


@pytest.mark.asyncio
async def test_delete_cascades_images(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    await _add_image(test_db, org_id=org_id, property_id=p.id)

    imgs_before = await dal.list_property_images(test_db, property_id=p.id)
    assert len(imgs_before) == 1

    await delete_property(test_db, org_id=org_id, property_id=p.id)

    imgs_after = await dal.list_property_images(test_db, property_id=p.id)
    assert imgs_after == []


@pytest.mark.asyncio
async def test_org_isolation_returns_404_not_403(test_db, seeded_admin):
    """Cross-org lookup returns 404 (property not found) — not 403.
    We never leak the existence of another tenant's property."""
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())

    with pytest.raises(HTTPException) as exc:
        await get_property(test_db, org_id=uuid.uuid4(), property_id=p.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected(test_db, seeded_admin):
    """`sold` is terminal — no transitions out."""
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    await _add_image(test_db, org_id=org_id, property_id=p.id)
    await publish_property(test_db, org_id=org_id, property_id=p.id)
    await mark_sold(test_db, org_id=org_id, property_id=p.id)

    with pytest.raises(HTTPException) as exc:
        await unpublish_property(test_db, org_id=org_id, property_id=p.id)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await archive_property(test_db, org_id=org_id, property_id=p.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_archive_then_unarchive(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    a = await archive_property(test_db, org_id=org_id, property_id=p.id)
    assert a.status == PropertyStatus.archived.value
    assert a.archived_at is not None

    u = await unarchive_property(test_db, org_id=org_id, property_id=p.id)
    assert u.status == PropertyStatus.draft.value
    assert u.archived_at is None


@pytest.mark.asyncio
async def test_list_returns_status_counts_and_pagination(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    for i in range(5):
        p = await create_property(
            test_db,
            org_id=org_id,
            actor_user_id=uuid.uuid4(),
            payload=_payload(title=f"Listing {i}"),
        )
        if i < 3:
            await _add_image(test_db, org_id=org_id, property_id=p.id)
            await publish_property(test_db, org_id=org_id, property_id=p.id)

    res = await list_properties(
        test_db,
        org_id=org_id,
        filters=PropertyListFilters(page=1, page_size=10),
    )
    assert res.total == 5
    assert res.status_counts.get("draft") == 2
    assert res.status_counts.get("published") == 3


@pytest.mark.asyncio
async def test_update_rejects_edits_on_archived(test_db, seeded_admin):
    org_id = seeded_admin["org"].id
    p = await create_property(test_db, org_id=org_id, actor_user_id=uuid.uuid4(), payload=_payload())
    await archive_property(test_db, org_id=org_id, property_id=p.id)

    with pytest.raises(HTTPException) as exc:
        await update_property(
            test_db,
            org_id=org_id,
            property_id=p.id,
            payload=PropertyUpdate(description="edit archived"),
        )
    assert exc.value.status_code == 409
