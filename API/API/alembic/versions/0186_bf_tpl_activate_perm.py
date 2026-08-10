"""Backfill ``templates.activate`` permission key on existing roles.

The key is registered into ``tbl_permissions`` automatically by the
app-startup module-registry sweep. Self-signup orgs created after
migration ``0185`` also get it grafted onto Owner + Admin by the
role-template registry in :mod:`core.permissions.role_templates`.

This migration fans the grant out to **existing** Owner + Admin
rows so live tenants pick the key up without restarting seeded
roles. Employee stays without it — they can be granted the key
explicitly on the Roles page if the org wants to broaden access.

Chains after ``0185_tpl_is_active``.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0186_bf_tpl_activate_perm"
down_revision: Union[str, None] = "0185_tpl_is_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY = "templates.activate"
_OWNER_ADMIN = ("Owner", "Admin")


def _register_key() -> None:
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, module, description)
        VALUES ('{_KEY}', 'templates', '{_KEY}')
        ON CONFLICT (key) DO NOTHING
        """
    )


def _grant_to(role_name: str) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM tbl_roles r
        CROSS JOIN tbl_permissions p
        WHERE r.name = '{role_name}'
          AND p.key = '{_KEY}'
        ON CONFLICT DO NOTHING
        """
    )


def _revoke_from(role_name: str) -> None:
    op.execute(
        f"""
        DELETE FROM tbl_role_permissions
        WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role_name}')
          AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{_KEY}')
        """
    )


def upgrade() -> None:
    _register_key()
    for role in _OWNER_ADMIN:
        _grant_to(role)


def downgrade() -> None:
    for role in _OWNER_ADMIN:
        _revoke_from(role)
    # Leave the key row in ``tbl_permissions`` — dropping it would
    # cascade-delete grants the operator may have added manually on
    # custom roles. Same pattern as ``0118``.
