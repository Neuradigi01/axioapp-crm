"""Reviews module descriptor.

Sidebar entry at `menu_position=540` (after Call Center at 520).
Permission keys `reviews.read` / `reviews.write` register on startup.
"""
from src.app.core.module_registry import ModuleDescriptor


MODULE = ModuleDescriptor(
    id="reviews",
    name="Reviews",
    icon="check",
    layer="core",
    route="/api/v1/reviews",
    frontend_route="/user/reviews",
    menu_position=540,
    permissions=["reviews.read", "reviews.write"],
)
