"""Module-registry auto-discovery picks up the furniture inventory module.

The registry walker steps into every `src.app.packs.<pack>/modules/<id>`
folder looking for a `module.py` that exposes a `MODULE` constant. This
test re-runs that discovery and asserts the inventory descriptor shows
up with the expected metadata.
"""

from __future__ import annotations

import pytest

from src.app.core.module_registry import discover_modules, registry


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Each test starts from a clean registry — `discover_modules` is
    idempotent but `registry.register` rejects duplicates."""
    saved = list(registry.list())
    registry.clear()
    yield
    registry.clear()
    for m in saved:
        registry.register(m)


def test_discover_finds_inventory_module():
    discover_modules()
    ids = [m.id for m in registry.list()]
    assert "inventory" in ids, f"`inventory` not in discovered modules: {ids}"


def test_inventory_module_metadata():
    discover_modules()
    inv = registry.get("inventory")
    assert inv is not None
    assert inv.name == "Inventory & Warehouse"
    assert inv.icon == "warehouse"
    assert inv.layer == "pack"
    assert inv.route == "/api/v1/inventory"
    assert inv.frontend_route == "/user/inventory"
    assert inv.menu_position == 20
    assert set(inv.permissions) == {
        "inventory.read",
        "inventory.write",
        "inventory.dispatch",
        "inventory.transfer",
    }


def test_inventory_hidden_from_users_without_perm():
    discover_modules()
    visible_ids = {m.id for m in registry.list_for_user(granted=[])}
    assert "inventory" not in visible_ids


def test_inventory_visible_to_user_with_read_perm():
    discover_modules()
    visible_ids = {m.id for m in registry.list_for_user(granted=["inventory.read"])}
    assert "inventory" in visible_ids
