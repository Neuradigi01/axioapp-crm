"""Module descriptor for the chatbots module.

The discovery walker in
:func:`core.module_registry.discover_modules` finds ``MODULE`` via
``getattr(mod, "MODULE", None)`` and registers it on startup — the
module file intentionally does not self-register (double-registration
crashes the lifespan hook).

Backend mount: ``/api/v1/chatbots`` (Step 3 router).
Frontend mount: ``/user/chatbots`` (Step 12 list page).

``menu_position=720`` places the sidebar entry right after
"Workflows" (710) inside the ``Automation`` section header —
templates → workflows → chatbots is the natural author flow.

Icon ``bot`` matches the ``lucide-bot`` frontend registration in
Step 12.
"""

from __future__ import annotations

from src.app.core.chatbots.permissions import ALL_KEYS
from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="chatbots",
    name="Chat Bots",
    icon="bot",
    layer="core",
    route="/api/v1/chatbots",
    frontend_route="/user/chatbots",
    permissions=list(ALL_KEYS),
    menu_position=720,
    section="Automation",
)
