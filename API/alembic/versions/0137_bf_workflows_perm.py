"""Backfill workflows permission keys on existing roles
(``tasks/workflows`` Step 3).

Six new keys (``workflows.read``, ``workflows.write``,
``workflows.activate``, ``workflows.clone``,
``workflows.view_analytics``, ``workflows.view_diagnostics``) get
registered into ``tbl_permissions`` automatically by the
app-startup module-registry sweep when
:mod:`core.workflows.module` is discovered. Self-signup orgs
created after this migration also get the keys grafted onto Owner
/ Admin / Employee by the role-template registry in
:mod:`core.permissions.role_templates`.

This migration fans those grants out to **existing** Owner /
Admin / Employee rows so live tenants pick the keys up without
restarting their seeded roles. Same fanout pattern as
``0118_bf_templates_perm`` + ``0127_bf_automations_perm``.

Owner + Admin get all six keys; Employee gets
``workflows.read`` + ``workflows.view_analytics`` only (sidebar
entry + analytics dashboard visible read-only) — matches the
role-template seed exactly.

Chains after ``0136_workflows_schema``.

Revision ID: 0137_bf_workflows_perm
Revises: 0136_workflows_schema
Create Date: 2026-06-29 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0137_bf_workflows_perm"
down_revision: Union[str, None] = "0136_workflows_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALL_KEYS = (
    "workflows.read",
    "workflows.write",
    "workflows.activate",
    "workflows.clone",
    "workflows.view_analytics",
    "workflows.view_diagnostics",
)
_OWNER_ADMIN = ("Owner", "Admin")
_EMPLOYEE = ("Employee",)
_EMPLOYEE_KEYS = (
    "workflows.read",
    "workflows.view_analytics",
)


def _grant_to(role_name: str, key: str) -> None:
    """Insert one (role_id, permission_id) row per matching role +
    permission key; idempotent via ON CONFLICT DO NOTHING. Keys
    not yet registered produce zero rows from the SELECT, so this
    is also safe to run before the lifespan module-sweep has
    registered them."""
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


def _register_key(key: str) -> None:
    """Idempotently insert the key into ``tbl_permissions``.

    The lifespan module-sweep also registers these keys at app
    startup, but the migration may run BEFORE the app process
    restarts. Registering here makes the migration self-sufficient
    — the role fanout below produces zero rows otherwise."""
    module = key.split(".", 1)[0]
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, module, description)
        VALUES ('{key}', '{module}', '{key}')
        ON CONFLICT (key) DO NOTHING
        """
    )


def upgrade() -> None:
    # 1. Register the six keys so the role fanout below has
    #    something to JOIN against. Idempotent.
    for key in _ALL_KEYS:
        _register_key(key)

    # 2. Owner + Admin: every key.
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _grant_to(role_name, key)
    # 3. Employee: read + view_analytics only.
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
        op.execute(
            f"DELETE FROM tbl_permissions WHERE key = '{key}'"
        )
