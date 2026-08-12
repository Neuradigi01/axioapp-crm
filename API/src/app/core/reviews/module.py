"""Reviews module descriptor.

Sidebar entry at `menu_position=620` — groups with Campaigns (600)
and Templates (610) under the "Engage" section. The previous
`menu_position=400` slotted it between the My Work modules
(Appointments/Conversations at 300-310 and Walk-ins/Tasks at
500-510), which — because the sidebar renders same-section RUNS
in menu_position order — surfaced "MY WORK" twice in the Owner
sidebar (Employees didn't see it because Reviews requires perms).

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
    menu_position=620,
    permissions=["reviews.read", "reviews.write"],
    section="Engage",
)
