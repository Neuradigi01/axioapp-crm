"""Campaigns module descriptor.

Sidebar entry at `menu_position=560` (after Reviews at 540).
Permission keys `campaigns.read`, `campaigns.write`, `campaigns.send`
register on startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="campaigns",
    name="Campaigns",
    icon="mail",
    layer="core",
    route="/api/v1/campaigns",
    frontend_route="/user/campaigns",
    menu_position=560,
    permissions=["campaigns.read", "campaigns.write", "campaigns.send"],
)
