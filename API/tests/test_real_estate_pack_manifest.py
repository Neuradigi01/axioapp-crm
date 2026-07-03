"""Real Estate CRM pack — manifest + catalog smoke tests.

Verifies `packs/real_estate/pack.yaml` parses cleanly, declares the
Property module's permission set, seeds the expected Leads pipeline /
roles, and the onboarding catalog auto-flips the tile from
`coming_soon` to `available` because the manifest exists on disk.

No `catalog_config.py` edit is required to activate the tile —
`core/packs/service.get_catalog()` scans `packs/*/pack.yaml` at
startup and marks any matching `template_id` as available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app.core.packs.loader import load_pack
from src.app.core.packs.service import get_catalog


def _pack_path() -> Path:
    candidates = [
        Path("src/app/packs/real_estate/pack.yaml"),
        Path("/app/src/app/packs/real_estate/pack.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"real_estate pack.yaml not found in any of: {candidates}")


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    get_catalog.cache_clear()
    yield
    get_catalog.cache_clear()


def test_manifest_parses_and_stamps_identity():
    manifest = load_pack(_pack_path())
    assert manifest.template_id == "real_estate"
    assert manifest.version == "1.0.0"
    assert manifest.display_name


def test_manifest_declares_property_module_permissions():
    manifest = load_pack(_pack_path())
    assert "property" in manifest.module_permissions
    perms = set(manifest.module_permissions["property"])
    assert {
        "property.read",
        "property.write",
        "property.publish",
        "property.archive",
        "property.delete",
    }.issubset(perms)


def test_manifest_leads_pipeline_has_won_and_lost_stages():
    manifest = load_pack(_pack_path())
    leads = next((p for p in manifest.pipelines if p.key == "leads"), None)
    assert leads is not None, "real_estate pack must ship a leads pipeline"
    wons = [s for s in leads.stages if s.is_won]
    losts = [s for s in leads.stages if s.is_lost]
    assert len(wons) == 1
    assert len(losts) >= 1


def test_manifest_seeds_five_curated_roles():
    manifest = load_pack(_pack_path())
    role_keys = {r.key for r in manifest.roles}
    assert role_keys == {"owner", "broker", "manager", "agent", "coordinator"}


def test_manifest_owner_grants_property_star():
    manifest = load_pack(_pack_path())
    owner = next(r for r in manifest.roles if r.key == "owner")
    assert "property.*" in owner.permissions


def test_manifest_declares_real_estate_lead_sources():
    manifest = load_pack(_pack_path())
    labels = {ls.label for ls in manifest.lead_sources}
    # Portal-specific labels prove this is the real-estate variant,
    # not the generic base pack.
    assert "99acres" in labels
    assert "MagicBricks" in labels


@pytest.mark.asyncio
async def test_catalog_marks_real_estate_available(layered_client):
    """With `packs/real_estate/pack.yaml` present, the catalog
    auto-flips the tile from `coming_soon` to `available`."""
    resp = await layered_client.get("/api/v1/packs/catalog")
    assert resp.status_code == 200
    by_id = {t["template_id"]: t for t in resp.json()["packs"]}
    assert "real_estate" in by_id
    assert by_id["real_estate"]["status"] == "available"
