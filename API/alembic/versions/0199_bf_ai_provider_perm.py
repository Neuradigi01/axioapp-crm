"""Backfill AI-provider permission key on existing Owner + Admin roles
(``tasks/ai-assistants`` Step 1).

The new key ``ai_providers.manage`` gates every mutation of the BYOK
key store (add / test / delete / reassign) + the org's daily/monthly
USD budget cap. Owner + Admin get it. Employee does NOT — BYOK keys
are a billing-sensitive surface (an insider with the key can drain
the org's OpenAI budget), and the RBAC track's role-template model
explicitly prefers the least-privilege default for money-adjacent
capabilities.

Self-signup orgs created after this migration pick the key up via
the role-template registry in
:mod:`core.permissions.role_templates` (updated in the same commit).
This migration fans it out to Owner + Admin rows on **existing** live
tenants so they get the sidebar tile without waiting for the app
restart. Same fanout pattern as ``0191_bf_chatbots_perm``.

Chains after ``0198_ai_provider_keys``.

Revision ID: 0199_bf_ai_provider_perm
Revises:     0198_ai_provider_keys
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0199_bf_ai_provider_perm"
down_revision: str | None = "0198_ai_provider_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_KEY: str = "ai_providers.manage"
_OWNER_ADMIN: tuple[str, ...] = ("Owner", "Admin")


def _register_key(key: str) -> None:
    """Idempotently insert the key into ``tbl_permissions``. The
    lifespan module-sweep also registers this key at app startup;
    registering here first lets the fanout JOIN find a row without
    depending on deploy order (``alembic upgrade`` may run before
    ``uvicorn start``)."""
    module = key.split(".", 1)[0]
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, module, description)
        VALUES ('{key}', '{module}', '{key}')
        ON CONFLICT (key) DO NOTHING
        """
    )


def _grant_to(role_name: str, key: str) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM tbl_roles r
        CROSS JOIN tbl_permissions p
        WHERE r.name = '{role_name}'
          AND p.key = '{key}'
        ON CONFLICT DO NOTHING
        """
    )


def _revoke_from(role_name: str, key: str) -> None:
    op.execute(
        f"""
        DELETE FROM tbl_role_permissions
        WHERE role_id IN (
            SELECT id FROM tbl_roles WHERE name = '{role_name}'
        )
        AND permission_id IN (
            SELECT id FROM tbl_permissions WHERE key = '{key}'
        )
        """
    )


def upgrade() -> None:
    _register_key(_KEY)
    for role_name in _OWNER_ADMIN:
        _grant_to(role_name, _KEY)


def downgrade() -> None:
    for role_name in _OWNER_ADMIN:
        _revoke_from(role_name, _KEY)
    op.execute(f"DELETE FROM tbl_permissions WHERE key = '{_KEY}'")
