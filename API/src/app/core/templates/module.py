"""Module descriptor for the central template library.

Registers the module's permission keys with the global permissions
registry on app startup (Rule 6) AND surfaces a sidebar entry for
every role that holds ``templates.read`` — Owner / Admin / Employee
get it via the role-template seed.

The route slug (`/api/v1/templates`) is the backend mount; the
frontend route slug (`/user/templates`) is where the SPA list page
mounts in Step 6. Until Step 6 lands, the sidebar entry exists but
the SPA route 404s — that's the only short-lived rough edge.
"""
from __future__ import annotations

from src.app.core.module_registry import ModuleDescriptor, registry
from src.app.core.templates.permissions import ALL_KEYS


MODULE = ModuleDescriptor(
    id="templates",
    name="Templates",
    icon="file-text",
    layer="core",
    route="/api/v1/templates",
    frontend_route="/user/templates",
    permissions=list(ALL_KEYS),
    # Step 5 — surface in the sidebar. 250 places "Templates" after
    # the high-traffic operational modules (Contacts / Leads /
    # Conversations sit in the 100–200 band) but before Settings /
    # Reports (600+). Owner can drag-reorder in the future Modules UI;
    # this is the default landing position.
    menu_position=250,
)

registry.register(MODULE)
