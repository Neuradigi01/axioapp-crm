"""Module descriptor for the per-org email-sender identity surface.

Reuses the ``email.accounts.manage`` permission from
:mod:`core.email` — the two modules together own outbound sender
management, so grouping them under one permission key keeps role
templates simple. ``menu_position=None`` keeps this out of the main
sidebar: it renders as a card inside Settings → Integrations rather
than as its own top-level page.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="email_senders",
    name="Email Senders",
    icon="send",
    layer="core",
    route="/api/v1/email-senders",
    frontend_route="/user/settings/integrations",
    menu_position=None,
    permissions=[
        "email.accounts.manage",
    ],
)
