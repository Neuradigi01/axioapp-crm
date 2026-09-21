"""Sender-setup module descriptor.

Registers the Owner-only ``email.sending_domains.manage`` permission
with the core RBAC registry at startup. The four sending-domains
endpoints (:mod:`router.sender_domains_router`) gate on this key.

``menu_position=None`` keeps this module out of the main sidebar — the
Sending Domains tab lives inside Settings → Email (frontend Step 7).
Legacy campaigns-only endpoints on ``/email-sender-setup`` remain
gated by ``email.accounts.admin`` from the ``email`` module descriptor.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="email_sender_setup",
    name="Sending Domains",
    icon="mail",
    layer="core",
    route="/api/v1/sender-domains",
    frontend_route="/user/settings/email-accounts",
    menu_position=None,
    permissions=[
        "email.sending_domains.manage",
    ],
)
