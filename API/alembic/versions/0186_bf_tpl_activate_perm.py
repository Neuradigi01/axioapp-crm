"""Backfill templates.activate permission key on existing Owner + Admin roles.

Chains after 0185_tpl_is_active. The key itself is registered into
tbl_permissions automatically by the app-startup module-registry sweep;
this migration fans the grant out to existing roles so live tenants
pick it up without restarting seeded roles.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0186_bf_tpl_activate_perm"
down_revision: Union[str, None] = "0185_tpl_is_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY = "templates.activate"
_OWNER_ADMIN = ("Owner", "Admin")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO tbl_permissions (key, module, description) "
        f"VALUES ('{_KEY}', 'templates', '{_KEY}') "
        f"ON CONFLICT (key) DO NOTHING"
    )
    for role in _OWNER_ADMIN:
        op.execute(
            f"INSERT INTO tbl_role_permissions (role_id, permission_id) "
            f"SELECT r.id, p.id FROM tbl_roles r CROSS JOIN tbl_permissions p "
            f"WHERE r.name = '{role}' AND p.key = '{_KEY}' "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    for role in _OWNER_ADMIN:
        op.execute(
            f"DELETE FROM tbl_role_permissions "
            f"WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role}') "
            f"  AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{_KEY}')"
        )
