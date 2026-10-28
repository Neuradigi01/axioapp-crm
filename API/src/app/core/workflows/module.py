"""Module descriptor for the workflows module.

Exposes the ``MODULE`` constant. The discovery walker in
:func:`core.module_registry.discover_modules` finds it via
``getattr(mod, "MODULE", None)`` and registers it — module files
intentionally don't register themselves (double-registration
crashes the lifespan).

Backend mount: ``/api/v1/workflows`` (Step 3 router).
Frontend mount: ``/user/workflows`` (Step 13 list page).

``menu_position=270`` places "Workflows" right after Automations
(260) and before Campaigns (300). Logical grouping — operators
build templates (250), wire single-event triggers (Automations,
260), then compose multi-step flowcharts (Workflows, 270).
"""

from __future__ import annotations

from src.app.core.module_registry import ModuleDescriptor
from src.app.core.workflows.permissions import ALL_KEYS

MODULE = ModuleDescriptor(
    id="workflows",
    name="Workflows",
    icon="git-branch",
    layer="core",
    route="/api/v1/workflows",
    frontend_route="/user/workflows",
    permissions=list(ALL_KEYS),
    menu_position=270,
)
