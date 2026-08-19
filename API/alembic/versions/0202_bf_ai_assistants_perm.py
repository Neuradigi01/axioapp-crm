"""Backfill AI Assistants permission keys onto existing roles
(``tasks/ai-assistants`` Step 5).

Two keys:

  * ``ai_assistants.view``   — Owner + Admin + Employee. Enables the
    sidebar entry + read-only surfaces (list, analytics, conversation
    history) for every role by default.
  * ``ai_assistants.manage`` — Owner + Admin. Every mutation +
    knowledge upload + embed-key issuance. Employee opts in via the
    Roles page (marketing-user delegation).

Same fanout pattern as ``0199_bf_ai_provider_perm``. Idempotent via
``ON CONFLICT DO NOTHING`` on the role_permissions insert.

Chains after ``0201_ai_assistants_schema``.

Revision ID: 0202_bf_ai_assistants_perm
Revises:     0201_ai_assistants_schema
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0202_bf_ai_assistants_perm"
down_revision: str | None = "0201_ai_assistants_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALL_KEYS: tuple[str, ...] = ("ai_assistants.view", "ai_assistants.manage")
_OWNER_ADMIN: tuple[str, ...] = ("Owner", "Admin")
_EMPLOYEE: tuple[str, ...] = ("Employee",)
_EMPLOYEE_KEYS: tuple[str, ...] = ("ai_assistants.view",)


def _register_key(key: str) -> None:
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
    for key in _ALL_KEYS:
        _register_key(key)

    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _grant_to(role_name, key)

    for role_name in _EMPLOYEE:
        for key in _EMPLOYEE_KEYS:
            _grant_to(role_name, key)


def downgrade() -> None:
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _revoke_from(role_name, key)
    for role_name in _EMPLOYEE:
        for key in _EMPLOYEE_KEYS:
            _revoke_from(role_name, key)
    for key in _ALL_KEYS:
        op.execute(f"DELETE FROM tbl_permissions WHERE key = '{key}'")
