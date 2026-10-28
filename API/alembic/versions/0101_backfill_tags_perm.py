"""Backfill settings.conversations.manage on existing Owner / Admin
(whatsapp-platform-upgrade Step 14 follow-up).

Same fanout pattern as 0095 / 0097. Tag CRUD gates on this key;
assignment continues to use `conversations.write` so junior roles can
apply existing tags without managing the library.

Idempotent via ``ON CONFLICT DO NOTHING``.

Chains after ``0100_conv_tags``.

Revision ID: 0101_backfill_tags_perm
Revises: 0100_conv_tags
Create Date: 2026-06-23 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0101_backfill_tags_perm"
down_revision: Union[str, None] = "0100_conv_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GRANT_KEY = "settings.conversations.manage"
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
