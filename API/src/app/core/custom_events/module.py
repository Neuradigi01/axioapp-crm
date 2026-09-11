"""Custom events module descriptor.

Menu position: nested under Settings (not a top-level sidebar entry).
Frontend routes it at `/user/settings/custom-events`.

Permissions:
  * ``custom_events.read``   — everyone with a login sees the picker
  * ``custom_events.manage`` — Owner/Admin: CRUD event definitions
  * ``custom_events.fire``   — any role that touches contacts
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="custom_events",
    name="Custom Events",
    icon="zap",
    layer="core",
    route="/api/v1/custom-events",
    frontend_route="/user/settings/custom-events",
    menu_position=None,
    permissions=[
        "custom_events.read",
        "custom_events.manage",
        "custom_events.fire",
    ],
)
