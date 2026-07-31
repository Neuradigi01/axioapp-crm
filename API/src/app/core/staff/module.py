"""Staff module descriptor.

Sidebar entry at `menu_position=450` (after Catalog, before
Reporting). Permission keys `staff.read`, `staff.write`,
`attendance.write` register on startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="staff",
    name="Staff",
    icon="users",
    layer="core",
    route="/api/v1/staff",
    frontend_route="/user/staff",
    menu_position=810,
    permissions=["staff.read", "staff.write", "attendance.write"],
    section="Business",
)
