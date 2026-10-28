"""Backfill whatsapp.automation.manage on existing Owner / Admin
(whatsapp-platform-upgrade Step 17 follow-up).

Same fanout pattern as 0095 / 0097 / 0101. Existing orgs need the
permission grant added once; signup orgs already pick it up from
`role_templates.py`.

Chains after ``0104_keyword_rules``.

Revision ID: 0105_backfill_auto_perm
Revises: 0104_keyword_rules
Create Date: 2026-06-23 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0105_backfill_auto_perm"
down_revision: Union[str, None] = "0104_keyword_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GRANT_KEY = "whatsapp.automation.manage"
_ROLE_NAMES = ("Owner", "Admin")


def upgrade() -> None:
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
