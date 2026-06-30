"""Unit tests for `ModuleRegistry` and `ModuleDescriptor` validation."""

from __future__ import annotations

import pytest

from src.app.core.module_registry import (
    ModuleDescriptor,
    ModuleRegistry,
    discover_modules,
    registry,
)


def _make_descriptor(**overrides) -> ModuleDescriptor:
    base = dict(
        id="contacts",
        name="Contacts",
        icon="users",
        layer="core",
        route="/api/v1/contacts",
        frontend_route="/contacts",
        permissions=["contacts.read"],
    )
    base.update(overrides)
    return ModuleDescriptor(**base)


def test_descriptor_rejects_bad_id():
    with pytest.raises(ValueError):
        _make_descriptor(id="Bad-ID")


def test_descriptor_rejects_route_without_slash():
    with pytest.raises(ValueError):
        _make_descriptor(route="api/v1/contacts")


def test_descriptor_rejects_bad_frontend_route():
    with pytest.raises(ValueError):
        _make_descriptor(frontend_route="contacts")


def test_descriptor_rejects_bad_layer():
    with pytest.raises(ValueError):
        _make_descriptor(layer="vendor")  # type: ignore[arg-type]


def test_descriptor_rejects_malformed_permission_key():
    with pytest.raises(ValueError):
        _make_descriptor(permissions=["contactsread"])


def test_register_duplicate_id_raises():
    r = ModuleRegistry()
    r.register(_make_descriptor())
    with pytest.raises(ValueError):
        r.register(_make_descriptor())


def test_list_sorts_by_menu_position_then_id():
    r = ModuleRegistry()
    r.register(_make_descriptor(id="zzz", menu_position=10))
    r.register(_make_descriptor(id="aaa", menu_position=20))
    r.register(_make_descriptor(id="mmm", menu_position=10))
    ids = [m.id for m in r.list()]
    assert ids == ["mmm", "zzz", "aaa"]


def test_list_for_user_filters_by_granted_permissions():
    r = ModuleRegistry()
    r.register(_make_descriptor(id="contacts", permissions=["contacts.read"]))
    r.register(_make_descriptor(id="settings", permissions=["settings.read"]))
    r.register(_make_descriptor(id="public", permissions=[]))

    visible = {m.id for m in r.list_for_user({"contacts.read"})}
    assert visible == {"contacts", "public"}  # public is always visible


def test_list_for_user_empty_grants_only_returns_public():
    r = ModuleRegistry()
    r.register(_make_descriptor(id="contacts", permissions=["contacts.read"]))
    r.register(_make_descriptor(id="public", permissions=[]))
    assert [m.id for m in r.list_for_user(set())] == ["public"]


def test_discover_modules_finds_settings_stub():
    """The Settings stub created in Step 1.8 should be discoverable."""
    registry.clear()
    discover_modules()
    ids = [m.id for m in registry.list()]
    assert "settings" in ids
