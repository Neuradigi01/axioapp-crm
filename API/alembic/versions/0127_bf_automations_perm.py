"""Backfill automation-engine permission keys on existing roles
(``tasks/automation-engine`` Step 3).

Three new keys (``automations.read``, ``automations.write``,
``automations.runs.read``) get registered into ``tbl_permissions``
automatically by the app-startup module-registry sweep when Step 7
lands ``core/automation/module.py``. Self-signup orgs created after
this migration also get the keys grafted onto Owner / Admin /
Employee by the role-template registry in
:mod:`core.permissions.role_templates`.

This migration fans those grants out to **existing** Owner / Admin /
Employee rows so live tenants pick the keys up without restarting
their seeded roles. Same fanout pattern as ``0118_bf_templates_perm``.

Owner + Admin get all three keys; Employee gets ``automations.read``
only (sidebar entry visible read-only) — matches the role-template
seed exactly.

Chains after ``0126_automation_schema``.

Revision ID: 0127_bf_automations_perm
Revises: 0126_automation_schema
Create Date: 2026-06-26 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0127_bf_automations_perm"
down_revision: Union[str, None] = "0126_automation_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALL_KEYS = (
    "automations.read",
    "automations.write",
    "automations.runs.read",
)
_OWNER_ADMIN = ("Owner", "Admin")
_EMPLOYEE = ("Employee",)


def _grant_to(role_name: str, key: str) -> None:
    """Insert one (role_id, permission_id) row per matching role +
    the permission key; idempotent via ON CONFLICT DO NOTHING. Keys
    that haven't been registered yet (extremely unlikely — the
    lifespan sweep runs before this migration is applicable, but
    defending here so the migration can run standalone) simply
    produce zero rows from the SELECT and nothing inserts."""
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
    # 1. Register the three keys so the role fanout below has
    #    something to JOIN against. Idempotent.
    for key in _ALL_KEYS:
        _register_key(key)

    # 2. Owner + Admin: every key.
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _grant_to(role_name, key)
    # 3. Employee: read only.
    for role_name in _EMPLOYEE:
        _grant_to(role_name, "automations.read")


def downgrade() -> None:
    # Revoke from Owner / Admin / Employee first; THEN drop the
    # permission rows themselves.
    for role_name in _OWNER_ADMIN:
        for key in _ALL_KEYS:
            _revoke_from(role_name, key)
    for role_name in _EMPLOYEE:
        _revoke_from(role_name, "automations.read")
    for key in _ALL_KEYS:
        op.execute(
            f"DELETE FROM tbl_permissions WHERE key = '{key}'"
        )
