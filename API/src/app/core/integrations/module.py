"""Integrations module descriptor.

Sidebar entry at `menu_position=900` (just before Settings at 999).
Registers the `settings.integrations.manage` permission with the core
RBAC registry at startup. The OAuth flows (Step 2 + 4) and webhook
receivers (Step 3 + 5) all gate on this single key — Owner-only by
default; Admin role template inherits it; Employee templates do not.

The name dropped the "Ad" qualifier — WhatsApp + email integrations
also live under this surface, so the broader label fits.
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="integrations",
    name="Integrations",
    icon="plug",
    layer="core",
    route="/api/v1/integrations",
    frontend_route="/user/integrations",
    menu_position=900,
    permissions=[
        "settings.integrations.manage",
        # whatsapp-platform-upgrade Step 8 — template management.
        # Read is wide (any operator on the Templates page); write
        # gates draft create/edit/duplicate/delete; submit is the
        # narrower "ship to Meta" action, defaulted off for junior
        # roles via the role template defaults.
        "whatsapp.templates.read",
        "whatsapp.templates.write",
        "whatsapp.templates.submit",
        # whatsapp-platform-upgrade Step 11 — business profile editor.
        # Single key gates both read + write since the page is a single
        # surface; junior roles inherit no access unless explicitly
        # granted (they don't get a useful read-only view).
        "whatsapp.business_profile.manage",
        # whatsapp-platform-upgrade Step 17 — automation (keyword rules
        # + future Step-18 assignment rules). Same Owner/Admin-only
        # model as business profile.
        "whatsapp.automation.manage",
        # whatsapp-platform-upgrade Step 22 — DPDP-ready opt-in. The
        # read of `/contacts/{id}/opt-in` is gated on `contacts.read`
        # (every staffer can see the consent state); this manage key
        # is what gates manual force-flip via the admin UI.
        "whatsapp.opt_in.manage",
        # whatsapp-platform-upgrade Step 25 — WhatsApp Flows manage
        # key. Gates the SPA library page + every create / publish /
        # test-send endpoint. Backfilled to Owner/Admin via the
        # migration so existing orgs can use Flows immediately.
        "whatsapp.flows.manage",
    ],
)
