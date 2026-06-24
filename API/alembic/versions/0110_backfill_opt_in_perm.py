"""Backfill whatsapp.opt_in.manage on existing Owner / Admin
(whatsapp-platform-upgrade Step 22 follow-up).

Same fanout pattern as 0095 / 0101 / 0105 / 0108. Existing orgs need
the permission grant added once; signup orgs already pick it up from
``role_templates.py``.

Chains after ``0109_opt_in_consent``.

Revision ID: 0110_bf_opt_in_perm
Revises: 0109_opt_in_consent
Create Date: 2026-06-24 02:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0110_bf_opt_in_perm"
down_revision: Union[str, None] = "0109_opt_in_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GRANT_KEY = "whatsapp.opt_in.manage"
_ROLE_NAMES = ("Owner", "Admin")


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, description, module)
        VALUES ('{_GRANT_KEY}', 'Manually override contact opt-in status', 'whatsapp')
        ON CONFLICT (key) DO NOTHING
        """
    )
    for role_name in _ROLE_NAMES:
        op.execute(
            f"""
            INSERT INTO tbl_role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM tbl_roles r
            CROSS JOIN tbl_permissions p
            WHERE r.name = '{role_name}'
              AND p.key = '{_GRANT_KEY}'
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    for role_name in _ROLE_NAMES:
        op.execute(
            f"""
            DELETE FROM tbl_role_permissions
            WHERE role_id IN (
                SELECT id FROM tbl_roles WHERE name = '{role_name}'
            )
            AND permission_id IN (
                SELECT id FROM tbl_permissions WHERE key = '{_GRANT_KEY}'
            )
            """
        )
