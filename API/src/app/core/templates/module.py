"""Module descriptor for the central template library.

Just exposes the ``MODULE`` constant. The discovery walker in
:func:`core.module_registry.discover_modules` finds it via
``getattr(mod, "MODULE", None)`` and registers it — module files
intentionally don't register themselves (double-registration crashes
the lifespan).

The route slug (`/api/v1/templates`) is the backend mount; the
frontend route slug (`/user/templates`) is where the SPA list page
mounts in Step 6. ``menu_position=250`` surfaces a sidebar entry for
every role holding ``templates.read``.
"""

from __future__ import annotations

from src.app.core.module_registry import ModuleDescriptor
from src.app.core.templates.permissions import ALL_KEYS

MODULE = ModuleDescriptor(
    id="templates",
    name="Templates",
    icon="file-text",
    layer="core",
    route="/api/v1/templates",
    frontend_route="/user/templates",
    permissions=list(ALL_KEYS),
    # 250 places "Templates" after the high-traffic operational modules
    # (Contacts / Leads / Conversations sit in the 100–200 band) but
    # before Settings / Reports (600+).
    menu_position=610,
    section="Engage",
)
