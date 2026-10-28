"""Module descriptor for the automation engine.

Just exposes the ``MODULE`` constant. The discovery walker in
:func:`core.module_registry.discover_modules` finds it via
``getattr(mod, "MODULE", None)`` and registers it — module files
intentionally don't register themselves (double-registration
crashes the lifespan; see the templates module post-Step-7 fix).

Backend mount: ``/api/v1/automations`` (Step 3 router).
Frontend mount: ``/user/automations`` (Step 7 list page).

``menu_position=260`` places "Automations" right after Templates
(250) and before Settings (600+). Logical grouping — operators
build templates, then attach them to triggers via the editor.
"""

from __future__ import annotations

from src.app.core.automation.permissions import ALL_KEYS
from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="automations",
    name="Automations",
    icon="workflow",
    layer="core",
    route="/api/v1/automations",
    frontend_route="/user/automations",
    permissions=list(ALL_KEYS),
    menu_position=260,
)
