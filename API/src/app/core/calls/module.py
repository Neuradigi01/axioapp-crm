"""Call-center module descriptor.

Sidebar entry at `menu_position=520` (after Conversations at 500).
Permission keys `calls.read`, `calls.write`, `calls.outcomes.manage`
register on startup via the standard module-registry pickup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="calls",
    name="Call Center",
    icon="phone",
    layer="core",
    route="/api/v1/calls",
    frontend_route="/user/calls",
    menu_position=520,
    permissions=["calls.read", "calls.write", "calls.outcomes.manage"],
)
