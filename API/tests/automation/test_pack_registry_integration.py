"""Tests for pack registry integration
(``tasks/automation-conditions/`` Step 7).

Covers the framework wiring — packs push events + resolvers into
the core registries via the public register APIs, auto-tagged with
their pack slug via a ContextVar the module-registry walker sets
before importing each pack's ``event_catalog.py``. The
``/event-types`` + ``/field-values`` endpoints filter by the caller
org's ``template_id`` so an org sees only core events + events
from packs it has installed.

Uses the furniture-pack skeleton (registered at boot by the
walker) as the concrete pack under test rather than a synthesized
fake pack — the walker's discovery of a real pack module in
``src.app.packs.furniture.modules.inventory.event_catalog`` is
itself part of what step-7 verifies.
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.automation import (
    CatalogEntry,
    EnumOption,
    FieldSpec,
    FieldType,
    enum_resolvers,
    event_catalog,
    register_event,
    register_field_resolver,
)
from src.app.core.automation._pack_context import (
    get_current_pack,
    reset_current_pack,
    set_current_pack,
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_packs_discovered():
    """Pytest doesn't spin up the FastAPI lifespan, so the pack
    event_catalog walker never runs unless we force it. Idempotent
    (event / resolver registrations are safe to re-run — same-
    callable calls are no-ops), so this is safe to autouse.
    """
    from src.app.core.module_registry import discover_modules

    discover_modules()


# --- pack ContextVar semantics --------------------------------------


def test_pack_context_default_is_none():
    """Outside any pack import, the context reads None so core
    registrations don't accidentally get tagged with a stale pack
    slug from a previous import."""
    assert get_current_pack() is None


def test_set_and_reset_pack_context_round_trip():
    """set_current_pack returns a token that reset_current_pack
    restores. Guards against a bad token leaking pack context into
    subsequent imports."""
    token = set_current_pack("fake_pack_test")
    try:
        assert get_current_pack() == "fake_pack_test"
    finally:
        reset_current_pack(token)
    assert get_current_pack() is None


# --- CatalogEntry pack tagging + visibility -------------------------


def test_register_event_inside_pack_context_auto_tags_pack_id():
    """When register_event runs while set_current_pack is active,
    the resulting CatalogEntry gets pack_id set automatically. This
    is what the walker does when importing pack event_catalog.py."""
    token = set_current_pack("__test_auto_tag")
    try:
        register_event(
            CatalogEntry(
                event_type="__test_auto_tag.event",
                label="Test",
                description="Test event for pack auto-tagging.",
                sample_payload={"foo": "bar"},
                condition_fields=(
                    FieldSpec(
                        path="foo",
                        label="Foo",
                        type=FieldType.text,
                        group="Test",
                    ),
                ),
            )
        )
    finally:
        reset_current_pack(token)

    entry = event_catalog.get_entry("__test_auto_tag.event")
    assert entry is not None
    assert entry.pack_id == "__test_auto_tag"


def test_is_visible_to_gates_pack_events_by_template_id():
    """Core entries visible everywhere; pack entries only visible
    when template_id matches their pack_id."""
    core_entry = event_catalog.get_entry("lead.created")
    assert core_entry is not None
    assert event_catalog.is_visible_to(core_entry, "furniture") is True
    assert event_catalog.is_visible_to(core_entry, "real_estate") is True
    assert event_catalog.is_visible_to(core_entry, None) is True

    furniture_entry = event_catalog.get_entry("inventory.item_low_stock")
    assert furniture_entry is not None, "furniture skeleton event should be in catalog"
    assert furniture_entry.pack_id == "furniture"
    assert event_catalog.is_visible_to(furniture_entry, "furniture") is True
    assert event_catalog.is_visible_to(furniture_entry, "real_estate") is False
    assert event_catalog.is_visible_to(furniture_entry, None) is False


# --- Resolver registry pack_owner_for -------------------------------


def test_pack_owner_for_returns_pack_slug_for_pack_registered_resolvers():
    """The furniture skeleton registered fp_warehouses +
    fp_item_categories inside its pack context — pack_owner_for
    should return "furniture" for both."""
    assert enum_resolvers.pack_owner_for("fp_warehouses") == "furniture"
    assert enum_resolvers.pack_owner_for("fp_item_categories") == "furniture"


def test_pack_owner_for_returns_none_for_core_resolvers():
    """Core resolvers registered outside any pack context stay
    pack_owner=None so they're visible to every org."""
    assert enum_resolvers.pack_owner_for("pipeline_stages") is None
    assert enum_resolvers.pack_owner_for("lead_sources") is None
    assert enum_resolvers.pack_owner_for("users") is None


def test_pack_owner_for_unknown_key_returns_none():
    """Missing keys read as core-owned (None) so the resolver
    lookup returns None cleanly instead of raising."""
    assert enum_resolvers.pack_owner_for(f"__missing_{uuid.uuid4().hex[:6]}") is None


# --- Walker error handling ------------------------------------------


def test_register_event_raises_on_drift_inside_pack_context():
    """A pack's event_catalog.py that declares a FieldSpec whose
    path doesn't resolve into the sample_payload MUST raise at
    import time. The walker catches this and re-raises so a broken
    pack fails app startup rather than silently missing from the
    picker."""
    token = set_current_pack("__test_bad_pack")
    try:
        with pytest.raises(ValueError, match="FieldSpec drift"):
            register_event(
                CatalogEntry(
                    event_type="__test_bad_pack.event",
                    label="Bad",
                    description="Test drift-guard fires inside pack context.",
                    sample_payload={"real_key": "value"},
                    condition_fields=(
                        FieldSpec(
                            path="typo_key",
                            label="Typo",
                            type=FieldType.text,
                            group="Test",
                        ),
                    ),
                )
            )
    finally:
        reset_current_pack(token)


# --- register_field_resolver auto-tagging ---------------------------


def test_register_field_resolver_inside_pack_context_auto_tags():
    """register_field_resolver called during a pack import gets
    tagged with the pack slug, so pack_owner_for returns the slug
    later."""
    key = f"__test_pack_resolver_{uuid.uuid4().hex[:6]}"

    async def resolver(_s, _o):
        return [EnumOption(value="x", label="X")]

    token = set_current_pack("__test_owner")
    try:
        register_field_resolver(key, resolver)
    finally:
        reset_current_pack(token)

    try:
        assert enum_resolvers.pack_owner_for(key) == "__test_owner"
    finally:
        enum_resolvers._unregister(key)  # noqa: SLF001


# --- Furniture skeleton coverage ------------------------------------


def test_furniture_skeleton_registers_event_and_resolvers():
    """Sanity — the discovery walker imported the furniture pack's
    inventory.event_catalog at boot and registered the skeleton
    entry + both resolvers. Guards against the walker regressing
    on the pack event-catalog second pass."""
    entry = event_catalog.get_entry("inventory.item_low_stock")
    assert entry is not None, "furniture skeleton event missing from catalog"
    assert entry.pack_id == "furniture"
    # Field specs preserved through the auto-tagging pass.
    paths = {s.path for s in entry.condition_fields}
    assert "item.sku" in paths
    assert "item.warehouse" in paths
    assert "item.category" in paths
    assert "item.stock_level" in paths
    # Warehouse spec's enum_resolver points at a registered resolver.
    warehouse_spec = next(s for s in entry.condition_fields if s.path == "item.warehouse")
    assert warehouse_spec.enum_resolver == "fp_warehouses"
    assert enum_resolvers.get_resolver("fp_warehouses") is not None
