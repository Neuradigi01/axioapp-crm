"""Module descriptor for the automation engine.

Just exposes the ``MODULE`` constant. The discovery walker in
:func:`core.module_registry.discover_modules` finds it via
``getattr(mod, "MODULE", None)`` and registers it — module files
intentionally don't register themselves (double-registration
crashes the lifespan; see the templates module post-Step-7 fix).

Backend mount: ``/api/v1/automations`` (Step 3 router).
Frontend mount: NONE at the module registry level as of
workflows-absorb-automation Step 3 (2026-08-05) — the frontend
``/user/automations/*`` routes still exist but only as redirects to
``/user/workflows/*``. See ``APP/src/app/features/user/user.routes.ts``.

``menu_position=None`` **hides** the module from the sidebar while
keeping it in the registry so its permission keys still register on
startup (RBAC edits + backend router remain callable, e.g. by admin
tooling). The workflows-absorb cutover consolidated the two lists;
the sidebar now shows a single "Workflows" entry under the
Automation section.
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
    menu_position=None,
    section="Automation",
)
