"""Module descriptor for the AI Assistants module.

Exposes the ``MODULE`` constant. The discovery walker in
:func:`core.module_registry.discover_modules` finds it via
``getattr(mod, "MODULE", None)`` and registers it.

Backend mount: ``/api/v1/ai-assistants`` (Step 6 router).
Frontend mount: ``/user/ai-assistants`` (Step 7 list page).

``menu_position=715`` places "AI Assistants" between Workflows
(``710``) and Chatbots (``720``) inside the ``Automation`` section.
Matches the manager-supplied Pabbly Chatflow IA the track locked
at plan time — separate module, peer of Workflows + Chatbots.
"""

from __future__ import annotations

from src.app.core.ai_assistants.permissions import ALL_KEYS
from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="ai_assistants",
    name="AI Assistants",
    icon="sparkles",
    layer="core",
    route="/api/v1/ai-assistants",
    frontend_route="/user/ai-assistants",
    permissions=list(ALL_KEYS),
    menu_position=715,
    section="Automation",
)
