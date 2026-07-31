"""Catalog module descriptor.

Sidebar entry at `menu_position=400`. Permission keys
`catalog.read` / `catalog.write` register on startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="catalog",
    name="Catalog",
    icon="package",
    layer="core",
    route="/api/v1/catalog",
    frontend_route="/user/catalog",
    menu_position=800,
    permissions=["catalog.read", "catalog.write"],
    section="Business",
)
