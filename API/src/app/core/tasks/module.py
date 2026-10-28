"""Tasks module descriptor.

Surfaces in the sidebar (`menu_position=300`) and registers both
permission keys. The "My Tasks" popover in the header is reached
from the bell-row icon, not from this sidebar entry — but the
sidebar entry still routes to a placeholder "all tasks" surface
intended for a future step.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="tasks",
    name="Tasks",
    icon="check-square",
    layer="core",
    route="/api/v1/tasks",
    frontend_route="/user/tasks",
    menu_position=300,
    permissions=["tasks.read", "tasks.write"],
)
