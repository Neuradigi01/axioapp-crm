"""Walk-ins module descriptor.

Sidebar entry at `menu_position=220` — sits between Contacts (200)
and Leads (250) since walk-ins are the typical *entry point* of the
showroom journey. Registers `walkins.read` / `walkins.write` so RBAC
seeds know about them at startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="walk_ins",
    name="Walk-ins",
    icon="footprints",
    layer="core",
    route="/api/v1/walk-ins",
    frontend_route="/user/walk-ins",
    menu_position=220,
    permissions=["walkins.read", "walkins.write", "walkins.reassign"],
)
