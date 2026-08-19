"""Permission keys for the AI Assistants module.

Two keys cover every action:

  * :data:`PERM_VIEW` — list / get assistants + read the analytics
    dashboard (Step 16) + view conversation history. Granted to
    Owner + Admin + Employee by default so the sidebar entry is
    visible to every role, but every mutation is gated by
    :data:`PERM_MANAGE` behind the frontend.

  * :data:`PERM_MANAGE` — create / update / archive / delete
    assistants, upload knowledge, edit prompt, test-fire,
    manage embed keys. Owner + Admin by default; Employee opts in
    via the Roles page (marketing-user delegation).

BYOK provider-key management (add key, delete key, budget cap) is
a **separate** permission — ``ai_providers.manage`` in
:mod:`core.integrations.ai.permissions`. Keeping them separate lets
an org grant assistant editing to a marketing user without also
handing over billing-sensitive key material.

Keys are registered into ``tbl_permissions`` by the app-startup
module-registry sweep (see :mod:`core.ai_assistants.module`) AND
by the Step-5 backfill migration ``0202_bf_ai_assistants_perm`` so
the role fanout finds them before the first restart.
"""

from __future__ import annotations

PERM_VIEW = "ai_assistants.view"
PERM_MANAGE = "ai_assistants.manage"


#: Every permission key this module declares.
ALL_KEYS: tuple[str, ...] = (PERM_VIEW, PERM_MANAGE)

#: Keys an Owner holds — every key.
OWNER_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Admin holds — every key.
ADMIN_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Employee holds by default — read-only view of the list
#: + analytics + conversation history. Mutation stays Owner/Admin
#: unless the Owner explicitly grants the key on a custom role.
EMPLOYEE_KEYS: tuple[str, ...] = (PERM_VIEW,)


__all__ = [
    "ADMIN_KEYS",
    "ALL_KEYS",
    "EMPLOYEE_KEYS",
    "OWNER_KEYS",
    "PERM_MANAGE",
    "PERM_VIEW",
]
