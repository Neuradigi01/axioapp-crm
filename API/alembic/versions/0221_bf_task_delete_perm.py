"""Backfill tasks.delete permission key on existing Owner + Admin roles.

Chains after 0220_bf_lead_followup_wf. The key itself is registered
into tbl_permissions automatically by the app-startup module-registry
sweep (once the module.py update in this branch ships), but this
migration also inserts it directly so a downgrade of the app code
doesn't leave existing roles without the grant.

Backfills the grant on every existing org's Owner + Admin roles.
Employee, Support Agent, and Sales Manager are intentionally excluded
— after this ships, they can still create + edit + complete tasks
but no longer delete them (single or bulk).

Revision ID: 0221_bf_task_delete_perm
Revises:     0220_bf_lead_followup_wf
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0221_bf_task_delete_perm"
down_revision: Union[str, None] = "0220_bf_lead_followup_wf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY = "tasks.delete"
_DELETING_ROLES = ("Owner", "Admin")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO tbl_permissions (key, module, description) "
        f"VALUES ('{_KEY}', 'tasks', "
        f"'Delete tasks (single + bulk). Owner/Admin only by default.') "
        f"ON CONFLICT (key) DO NOTHING"
    )
    for role in _DELETING_ROLES:
        op.execute(
            f"INSERT INTO tbl_role_permissions (role_id, permission_id) "
            f"SELECT r.id, p.id FROM tbl_roles r CROSS JOIN tbl_permissions p "
            f"WHERE r.name = '{role}' AND p.key = '{_KEY}' "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    for role in _DELETING_ROLES:
        op.execute(
            f"DELETE FROM tbl_role_permissions "
            f"WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role}') "
            f"  AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{_KEY}')"
        )
