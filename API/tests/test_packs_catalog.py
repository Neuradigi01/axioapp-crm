"""Tests for `GET /api/v1/packs/catalog`.

The catalog composes static tile metadata (`catalog_config.py`) with
on-disk pack discovery (`packs/*/pack.yaml`). Real packs surface as
`status="available"`; configured-but-not-built packs surface as
`status="coming_soon"`.
"""

from __future__ import annotations

import pytest

from src.app.core.packs.catalog_config import CATALOG_PACKS
from src.app.core.packs.service import get_catalog


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    """`get_catalog` is process-cached. Reset between tests so each one
    sees a fresh build (cheap — no DB hit)."""
    get_catalog.cache_clear()
    yield
    get_catalog.cache_clear()


@pytest.mark.asyncio
async def test_catalog_returns_200_no_auth_required(layered_client):
    resp = await layered_client.get("/api/v1/packs/catalog")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_catalog_includes_real_packs_as_available(layered_client):
    resp = await layered_client.get("/api/v1/packs/catalog")
    by_id = {t["template_id"]: t for t in resp.json()["packs"]}
    # Furniture pack ships with the repo (`packs/furniture/pack.yaml`).
    assert "furniture" in by_id
    assert by_id["furniture"]["status"] == "available"
    # Real Estate pack ships with the repo (`packs/real_estate/pack.yaml`).
    assert "real_estate" in by_id
    assert by_id["real_estate"]["status"] == "available"
    # The "Core CRM" tile is keyed by `base` because that is the on-disk
    # template_id at `packs/base/pack.yaml`. Display name is "Core CRM".
    assert "base" in by_id
    assert by_id["base"]["status"] == "available"
    assert by_id["base"]["name"] == "Core CRM"


@pytest.mark.asyncio
async def test_catalog_marks_placeholders_coming_soon(layered_client):
    resp = await layered_client.get("/api/v1/packs/catalog")
    by_id = {t["template_id"]: t for t in resp.json()["packs"]}
    for placeholder_id in (
        "clinic",
        "sales",
        "automotive",
        "salon",
        "fitness",
        "education",
        "hospitality",
    ):
        assert placeholder_id in by_id, f"placeholder {placeholder_id} missing from catalog"
        assert by_id[placeholder_id]["status"] == "coming_soon", (
            f"{placeholder_id} should be coming_soon (no pack.yaml exists)"
        )


@pytest.mark.asyncio
async def test_catalog_sorted_by_display_order(layered_client):
    resp = await layered_client.get("/api/v1/packs/catalog")
    orders = [t["display_order"] for t in resp.json()["packs"]]
    assert orders == sorted(orders), "catalog must be sorted by display_order"


@pytest.mark.asyncio
async def test_catalog_tile_shape_stable(layered_client):
    """Every tile carries the same keys."""
    resp = await layered_client.get("/api/v1/packs/catalog")
    expected_keys = {
        "template_id",
        "name",
        "description",
        "icon",
        "status",
        "default_currency",
        "default_tax_rate",
        "modules_preview",
        "display_order",
    }
    for tile in resp.json()["packs"]:
        assert set(tile.keys()) == expected_keys, (
            f"tile {tile.get('template_id')!r} has unexpected key set: {set(tile.keys())}"
        )


@pytest.mark.asyncio
async def test_catalog_returns_all_configured_packs(layered_client):
    """Every entry in CATALOG_PACKS appears in the response exactly once."""
    resp = await layered_client.get("/api/v1/packs/catalog")
    returned_ids = [t["template_id"] for t in resp.json()["packs"]]
    configured_ids = [entry["template_id"] for entry in CATALOG_PACKS]
    assert sorted(returned_ids) == sorted(configured_ids)
    assert len(returned_ids) == len(set(returned_ids)), (
        "no template_id should appear twice in the catalog"
    )
