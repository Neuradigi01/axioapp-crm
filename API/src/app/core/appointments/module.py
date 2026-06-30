"""Appointments module descriptor.

Sidebar entry at `menu_position=350`. Frontend route lands on the
calendar view (Step 2.14). Permission keys register at startup.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="appointments",
    name="Appointments",
    icon="calendar",
    layer="core",
    route="/api/v1/appointments",
    frontend_route="/user/appointments",
    menu_position=350,
    permissions=[
        "appointments.read",
        "appointments.write",
        "appointments.reassign",
    ],
)
