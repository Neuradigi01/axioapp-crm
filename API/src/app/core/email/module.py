"""Email-accounts module descriptor.

Registers `email.accounts.manage` + `email.accounts.admin` with the
core RBAC registry at startup. The Gmail (Step 2) and Microsoft
Graph (Step 3) connect flows + the Conversations email-channel
adapter (Step 5) all gate on these keys.

`menu_position=None` keeps this module out of the main sidebar —
account management lives as a tab inside Settings → Email Accounts
(Step 9 of this track).
"""

from src.app.core.module_registry import ModuleDescriptor

MODULE = ModuleDescriptor(
    id="email",
    name="Email Accounts",
    icon="mail",
    layer="core",
    route="/api/v1/email",
    frontend_route="/user/settings/email-accounts",
    menu_position=None,
    permissions=[
        "email.accounts.manage",
        "email.accounts.admin",
    ],
)
