"""Backfill chatbot permission keys on existing roles
(``tasks/chatbot-builder`` Step 3).

The four new keys (``chatbots.view``, ``chatbots.edit``,
``chatbots.publish``, ``chatbots.delete``) get registered into
``tbl_permissions`` automatically by the app-startup module-registry
sweep. Self-signup orgs created after this migration also get the
keys grafted onto Owner / Admin / Employee by the role-template
registry in :mod:`core.permissions.role_templates`.

This migration fans those grants out to **existing** Owner / Admin /
Employee rows on live tenants so they pick the keys up without
waiting for a restart. Same fanout pattern as ``0118_bf_templates_perm``
and ``0187_bf_task_assign_perm``.

Owner + Admin get all four keys; Employee gets ``chatbots.view``
only — matches the role-template seed exactly.

Chains after ``0190_chatbot_versions``.

Revision ID: 0191_bf_chatbots_perm
Revises:     0190_chatbot_versions
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0191_bf_chatbots_perm"
down_revision: str | None = "0190_chatbot_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALL_KEYS: tuple[str, ...] = (
    "chatbots.view",
    "chatbots.edit",
    "chatbots.publish",
    "chatbots.delete",
)
_OWNER_ADMIN: tuple[str, ...] = ("Owner", "Admin")
_EMPLOYEE: tuple[str, ...] = ("Employee",)
_EMPLOYEE_KEYS: tuple[str, ...] = ("chatbots.view",)


def _register_key(key: str) -> None:
    """Idempotently insert the key into ``tbl_permissions``. The
    lifespan module-sweep also registers these keys at app startup,
    but the migration may run BEFORE the app process restarts
    (deploy order: ``alembic upgrade`` → ``uvicorn start``).
    Registering here makes the migration self-sufficient — the role
    fanout below produces zero rows otherwise."""
    module = key.split(".", 1)[0]
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, module, description)
        VALUES ('{key}', '{module}', '{key}')
        ON CONFLICT (key) DO NOTHING
        """
    )


def _grant_to(role_name: str, key: str) -> None:
    """Insert one ``(role_id, permission_id)`` row per matching role
    + permission key; idempotent via ``ON CONFLICT DO NOTHING``.
    Keys not yet registered produce zero SELECT rows and nothing
    inserts."""
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
    # 1. Register the four keys so the role fanout has something to
    #    JOIN against.
    for key in _ALL_KEYS:
        _register_key(key)

    # 2. Owner + Admin: every key.
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _grant_to(role_name, key)

    # 3. Employee: view only.
    for role_name in _EMPLOYEE:
        for key in _EMPLOYEE_KEYS:
            _grant_to(role_name, key)


def downgrade() -> None:
    # Revoke from Owner / Admin / Employee first; THEN drop the
    # permission rows themselves.
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _revoke_from(role_name, key)
    for role_name in _EMPLOYEE:
        for key in _EMPLOYEE_KEYS:
            _revoke_from(role_name, key)
    for key in _ALL_KEYS:
        op.execute(f"DELETE FROM tbl_permissions WHERE key = '{key}'")
