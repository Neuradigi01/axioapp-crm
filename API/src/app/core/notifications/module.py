"""Notifications module descriptor.

`menu_position=None` keeps this module out of the sidebar — the
notifications UI lives in the header's bell-icon popover, not as a
top-level entry. No permission keys are registered because every
authenticated user is allowed to read and manage their own
notifications; per-resource scoping happens inside the service.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="notifications",
    name="Notifications",
    icon="bell",
    layer="core",
    route="/api/v1/notifications",
    frontend_route="/user",
    menu_position=None,
    permissions=[],
)
