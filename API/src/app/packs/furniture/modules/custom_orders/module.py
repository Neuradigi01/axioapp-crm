"""Furniture-pack: Custom Orders module descriptor.

Auto-discovered at startup by the module registry walker — same
convention as the inventory module.

`menu_position=30` slots Custom Orders right after Inventory (20) in
the sidebar. The three permissions (`read`, `write`, `move`) line up
with the per-endpoint gates in `router.py`.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="custom_orders",
    name="Custom Orders",
    icon="ruler",
    layer="pack",
    route="/api/v1/custom-orders",
    frontend_route="/user/custom-orders",
    menu_position=305,
    permissions=[
        "custom_orders.read",
        "custom_orders.write",
        "custom_orders.move",
    ],
    section="My Work",
)
