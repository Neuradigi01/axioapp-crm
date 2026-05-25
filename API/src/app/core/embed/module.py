"""Embeddable widget module descriptor.

The widget itself runs on the customer's own website — there is no
in-CRM sidebar entry for it. Owner management lives as a tab inside
Settings → Integrations (Step 4 of this track). So `menu_position=None`
keeps the module out of the sidebar while still registering its
permission key on startup.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="embed",
    name="Embeddable Widget",
    icon="code",
    layer="core",
    route="/api/v1/embed",
    frontend_route="/user/settings/integrations/embed",
    menu_position=None,
    permissions=["settings.integrations.embed.manage"],
)
