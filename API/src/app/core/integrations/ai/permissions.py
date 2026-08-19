"""Permission key for the AI-provider BYOK store.

One key covers every mutation of stored keys (add / test / delete /
reassign) + the org's daily/monthly USD budget cap. Owner + Admin
hold it by default; Employee does NOT — BYOK keys are a
billing-sensitive surface (an insider with a stored key can drain
the org's OpenAI budget), so the RBAC track's least-privilege default
for money-adjacent capabilities applies.

The key is registered into ``tbl_permissions`` by the app-startup
module-registry sweep (see :mod:`core.integrations.ai.module` if a
future module descriptor is added) AND by the backfill migration
``0199_bf_ai_provider_perm``. Both are idempotent.

Sourced from one place so :mod:`core.permissions.role_templates`
and the backfill migration import the string by name instead of
hard-coding it.
"""

from __future__ import annotations

PERM_MANAGE = "ai_providers.manage"

#: Every permission key this sub-module declares.
ALL_KEYS: tuple[str, ...] = (PERM_MANAGE,)

#: Keys an Owner holds — every key.
OWNER_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Admin holds — every key.
ADMIN_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Employee holds — none. Billing-sensitive surface.
EMPLOYEE_KEYS: tuple[str, ...] = ()


__all__ = [
    "ADMIN_KEYS",
    "ALL_KEYS",
    "EMPLOYEE_KEYS",
    "OWNER_KEYS",
    "PERM_MANAGE",
]
