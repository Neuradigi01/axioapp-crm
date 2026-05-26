"""Ad-integrations module descriptor.

Registers the `settings.integrations.manage` permission with the core
RBAC registry at startup. The OAuth flows (Step 2 + 4) and webhook
receivers (Step 3 + 5) all gate on this single key — Owner-only by
default; Admin role template inherits it; Employee templates do not.

`menu_position=None` keeps this module out of the main sidebar — it
lives as a tab inside Settings → Integrations (the existing tab gets
wired to the new Google Ads / Meta Ads cards in Step 7).
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="integrations",
    name="Ad Integrations",
    icon="plug",
    layer="core",
    route="/api/v1/integrations",
    frontend_route="/user/settings/integrations",
    menu_position=None,
    permissions=["settings.integrations.manage"],
)
