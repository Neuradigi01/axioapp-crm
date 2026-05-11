"""Settings module descriptor.

Stub registration so the sidebar always renders at least one entry
while we build out the rest of core in later steps.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="settings",
    name="Settings",
    icon="cog",
    layer="core",
    route="/api/v1/settings",
    frontend_route="/user/settings",
    menu_position=999,
    permissions=["settings.read", "settings.write"],
)
