"""Module descriptor for the central template library.

Registers the module's permission keys with the global permissions
registry on app startup (Rule 6 — every module declares its
permission keys). ``menu_position=None`` so this descriptor does NOT
surface a sidebar entry yet — Step 5 of the track flips the position
+ adds the Lucide icon + final menu copy when the test-send endpoint
and the SPA's list page land together.

The route slug (`/api/v1/templates`) and the frontend route slug
(`/user/templates`) are declared here so they match across the rest
of the module's surfaces even before the sidebar visibility flips on.
"""
from __future__ import annotations

from src.app.core.module_registry import ModuleDescriptor, registry
from src.app.core.templates.permissions import ALL_KEYS


MODULE = ModuleDescriptor(
    id="templates",
    name="Templates",
    # Icon is set here to the final Lucide id so Step 5's UI work
    # doesn't need a follow-up edit. Sidebar visibility is gated by
    # ``menu_position`` — None until Step 5 flips it.
    icon="file-text",
    layer="core",
    route="/api/v1/templates",
    frontend_route="/user/templates",
    permissions=list(ALL_KEYS),
    # Step 5 sets a real menu position; until then the registry holds
    # the module for permission discovery only.
    menu_position=None,
)

registry.register(MODULE)
