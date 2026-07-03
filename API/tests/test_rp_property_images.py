"""Property image gallery — service tests.

Covers the multi-image lifecycle: upload batch validation, delete,
reorder, set-featured. The storage backend is patched to a tempdir per
test so real filesystem I/O happens but doesn't leak between cases.
"""

from __future__ import annotations

import io
import struct
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from src.app.packs.real_estate.modules.property import data_access as dal
from src.app.packs.real_estate.modules.property.constants import (
    PropertyCategory,
    PropertyType,
)
from src.app.packs.real_estate.modules.property.schemas import PropertyCreate
from src.app.packs.real_estate.modules.property.service import (
    create_property,
    delete_property,
    delete_property_image,
    reorder_property_images,
    set_featured_image,
    upload_property_images,
)


def _jpeg_bytes(w: int = 80, h: int = 60, color: tuple[int, int, int] = (200, 100, 50)) -> bytes:
    """Real JPEG bytes libmagic will identify. Pillow is already a
    transitive test dep via the image validator's environment."""
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _patch_storage(tmp_path, monkeypatch):
    """Route every `get_storage()` call to a fresh per-test tempdir so
    real files land somewhere the test can inspect + assert on."""
    from src.app.shared.storage import get_storage
    from src.app.shared.storage.local import LocalStorage

    get_storage.cache_clear()
    monkeypatch.setattr(
        "src.app.shared.storage.get_storage",
        lambda: LocalStorage(root=str(tmp_path)),
    )
    # Also patch the callers' rebinds — service.py imports `get_storage`
    # into its own namespace, so we monkeypatch that binding directly.
    monkeypatch.setattr(
        "src.app.packs.real_estate.modules.property.service.get_storage",
        lambda: LocalStorage(root=str(tmp_path)),
    )
    yield tmp_path
    get_storage.cache_clear()


async def _make_property(db, seeded_admin) -> uuid.UUID:
    p = await create_property(
        db,
        org_id=seeded_admin["org"].id,
        actor_user_id=uuid.uuid4(),
        payload=PropertyCreate(
            title="Sea-facing 3 BHK",
            property_type=PropertyType.apartment,
            category=PropertyCategory.residential_sale,
        ),
    )
    return p.id


@pytest.mark.asyncio
async def test_upload_three_images_first_is_featured(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    files = [
        (f"pic-{i}.jpg", _jpeg_bytes(color=(200 - 10 * i, 100, 50)), "image/jpeg")
        for i in range(3)
    ]
    inserted = await upload_property_images(
        test_db, org_id=seeded_admin["org"].id, property_id=pid, files=files
    )
    assert len(inserted) == 3
    featured = [i for i in inserted if i.is_featured]
    assert len(featured) == 1
    assert inserted[0].is_featured  # first uploaded becomes featured

    # All three files are physically on disk under the tempdir.
    org_id = seeded_admin["org"].id
    files_on_disk = list((_patch_storage / str(org_id) / "property" / str(pid)).glob("*.jpg"))
    assert len(files_on_disk) == 3


@pytest.mark.asyncio
async def test_upload_invalid_file_rejected(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    with pytest.raises(HTTPException) as exc:
        await upload_property_images(
            test_db,
            org_id=seeded_admin["org"].id,
            property_id=pid,
            files=[("evil.svg", b"<svg xmlns='x'/>", "image/svg+xml")],
        )
    assert exc.value.status_code == 422

    # DB has no image rows and no files on disk.
    images = await dal.list_property_images(test_db, property_id=pid)
    assert images == []
    org_id = seeded_admin["org"].id
    prop_dir = _patch_storage / str(org_id) / "property" / str(pid)
    assert not prop_dir.exists() or not list(prop_dir.iterdir())


@pytest.mark.asyncio
async def test_reorder_persists_display_order(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    inserted = await upload_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        files=[(f"p{i}.jpg", _jpeg_bytes(color=(50 * i, 50, 50)), "image/jpeg") for i in range(3)],
    )
    reversed_ids = [i.id for i in reversed(inserted)]
    fresh = await reorder_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        image_ids=reversed_ids,
    )
    assert [i.id for i in fresh] == reversed_ids
    assert [i.display_order for i in fresh] == [0, 1, 2]


@pytest.mark.asyncio
async def test_reorder_with_mismatched_ids_rejected(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    inserted = await upload_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        files=[("p.jpg", _jpeg_bytes(), "image/jpeg")],
    )
    with pytest.raises(HTTPException) as exc:
        await reorder_property_images(
            test_db,
            org_id=seeded_admin["org"].id,
            property_id=pid,
            image_ids=[uuid.uuid4()],  # not the actual id
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_featured_promotes_next(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    inserted = await upload_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        files=[(f"p{i}.jpg", _jpeg_bytes(color=(50 * i, 50, 50)), "image/jpeg") for i in range(3)],
    )
    featured_id = inserted[0].id  # first uploaded is featured by default
    await delete_property_image(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        image_id=featured_id,
    )
    remaining = await dal.list_property_images(test_db, property_id=pid)
    assert len(remaining) == 2
    assert any(i.is_featured for i in remaining)


@pytest.mark.asyncio
async def test_set_featured_exclusive(test_db, seeded_admin, _patch_storage):
    """After set_featured on image B, exactly one image (B) has
    is_featured=True. Partial unique index would raise IntegrityError
    if the service left two rows featured at commit time."""
    pid = await _make_property(test_db, seeded_admin)
    inserted = await upload_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        files=[(f"p{i}.jpg", _jpeg_bytes(color=(50 * i, 50, 50)), "image/jpeg") for i in range(3)],
    )
    target = inserted[2].id
    await set_featured_image(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        image_id=target,
    )
    images = await dal.list_property_images(test_db, property_id=pid)
    featured = [i for i in images if i.is_featured]
    assert len(featured) == 1
    assert featured[0].id == target


@pytest.mark.asyncio
async def test_delete_property_cascades_files_and_rows(test_db, seeded_admin, _patch_storage):
    pid = await _make_property(test_db, seeded_admin)
    await upload_property_images(
        test_db,
        org_id=seeded_admin["org"].id,
        property_id=pid,
        files=[("p.jpg", _jpeg_bytes(), "image/jpeg")],
    )
    org_id = seeded_admin["org"].id
    prop_dir = _patch_storage / str(org_id) / "property" / str(pid)
    assert prop_dir.exists() and any(prop_dir.iterdir())

    await delete_property(test_db, org_id=org_id, property_id=pid)

    # DB rows gone (cascade).
    remaining = await dal.list_property_images(test_db, property_id=pid)
    assert remaining == []
    # Directory swept.
    assert not prop_dir.exists()
