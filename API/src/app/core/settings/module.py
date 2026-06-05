"""Settings module descriptor.

`always_visible=True` keeps the Settings entry in every authenticated
user's sidebar — even Employees who don't hold `settings.read` — so
they can reach the per-user Notifications preferences tab. Admin-only
tabs (Team, Roles, Integrations, Standard Fields, Embed Widget,
AI Settings, Store Profile, Custom Fields) are individually gated
inside the settings page; see `settings-page.component.ts::TABS`.
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
    always_visible=True,
)
