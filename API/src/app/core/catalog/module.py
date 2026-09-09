"""Catalog module descriptor.

Sidebar entry at `menu_position=800`. Permission keys register on
startup: ``catalog.read`` (list/get), ``catalog.write`` (create /
update / delete / images / bulk-import), ``catalog.publish`` (publish
/ unpublish), ``catalog.archive`` (archive / unarchive).
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
    permissions=[
        "catalog.read",
        "catalog.write",
        "catalog.publish",
        "catalog.archive",
    ],
    section="Business",
)
