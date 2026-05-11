"""Custom Fields module descriptor.

`menu_position=None` keeps this module out of the sidebar. The Custom
Fields admin UI is reached from inside Settings (rule 5 — sidebar is
a registry; hidden positions are honoured by the registry).

Permissions still register on startup via the module-registry sweep,
so `custom_fields.read` / `.write` show up in the global permission
registry without any per-module hand-wiring.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="custom_fields",
    name="Custom Fields",
    icon="form-field",
    layer="core",
    route="/api/v1/custom-fields",
    frontend_route="/user/settings/custom-fields",
    menu_position=None,
    permissions=["custom_fields.read", "custom_fields.write"],
)
