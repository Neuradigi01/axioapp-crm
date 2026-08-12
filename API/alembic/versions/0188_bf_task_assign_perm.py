"""Backfill tasks.assign_others permission key on existing
Owner / Admin / Sales Manager roles.

Chains after 0187_bf_task_workflows. The key itself is registered
into tbl_permissions automatically by the app-startup module-registry
sweep (once the module.py update in this branch ships), but this
migration also inserts it directly so a downgrade of the app code
doesn't leave existing roles without the grant.

Backfills the grant on every existing org's Owner, Admin, and Sales
Manager roles. Employee and Support Agent are intentionally excluded
— they can only create tasks for themselves after this ships.

Revision ID: 0188_bf_task_assign_perm
Revises:     0187_bf_task_workflows
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0188_bf_task_assign_perm"
down_revision: Union[str, None] = "0187_bf_task_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY = "tasks.assign_others"
_DELEGATING_ROLES = ("Owner", "Admin", "Sales Manager")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO tbl_permissions (key, module, description) "
        f"VALUES ('{_KEY}', 'tasks', "
        f"'Delegate tasks to other users (Owner/Admin only by default)') "
        f"ON CONFLICT (key) DO NOTHING"
    )
    for role in _DELEGATING_ROLES:
        op.execute(
            f"INSERT INTO tbl_role_permissions (role_id, permission_id) "
            f"SELECT r.id, p.id FROM tbl_roles r CROSS JOIN tbl_permissions p "
            f"WHERE r.name = '{role}' AND p.key = '{_KEY}' "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    for role in _DELEGATING_ROLES:
        op.execute(
            f"DELETE FROM tbl_role_permissions "
            f"WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role}') "
            f"  AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{_KEY}')"
        )
