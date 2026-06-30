"""Standard Fields module descriptor.

`menu_position=None` keeps this module out of the sidebar — the
management UI is reached from inside Settings (rule 5). The discovery
sweep still registers the `settings.standard_fields.manage` permission
key in the global registry on startup, so RBAC can grant it.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="standard_fields",
    name="Standard Fields",
    icon="form-field",
    layer="core",
    route="/api/v1/standard-fields",
    frontend_route="/user/settings/standard-fields",
    menu_position=None,
    permissions=["settings.standard_fields.manage"],
)
