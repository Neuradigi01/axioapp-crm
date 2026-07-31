"""Furniture-pack: Field Operations module descriptor."""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="field_ops",
    name="Field Operations",
    icon="map-pin",
    layer="pack",
    route="/api/v1/field-visits",
    frontend_route="/user/field-ops",
    menu_position=315,
    permissions=[
        "field_visits.read",
        "field_visits.write",
    ],
    section="My Work",
)
