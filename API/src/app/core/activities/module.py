"""Activities module descriptor.

Activities don't render as a standalone sidebar entry — they appear
as a tab inside every entity's detail page (contact, lead, …). So
`menu_position=None` keeps this module out of the sidebar while still
registering its permission keys on startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="activities",
    name="Activities",
    icon="activity",
    layer="core",
    route="/api/v1/activities",
    frontend_route="/user/contacts",
    menu_position=None,
    permissions=["activities.read", "activities.write"],
)
