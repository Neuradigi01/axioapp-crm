"""Copy users → tbl_user_login

Copies every row from `users` into `tbl_user_login`, preserving the
original UUID identity in `legacy_uuid` so the existing
`demo_credentials.user_id` UUID FK keeps validating via a join on
`legacy_uuid`.

- `user_id` (TEXT, UNIQUE) is synthesised from the UUID (`'usr_' ||
  hex-of-uuid`) so it won't collide with the legacy USR29684795 row.
- `two_factor_enabled` is forced to FALSE because the source `users`
  table doesn't carry 2FA columns and FurnitureCRM auth doesn't use
  them. The legacy row's setting is unaffected.
- `WHERE NOT EXISTS (... legacy_uuid = u.id)` makes the migration
  idempotent: re-running is a no-op.

No UPDATEs and no constraint changes; the `users` table is left
physically intact as a 2-week safety net.

Revision ID: 0032_users_to_tbl_user_login
Revises: 0031_tbl_user_login_for_crm
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0032_users_to_tbl_user_login"
down_revision: Union[str, None] = "0031_tbl_user_login_for_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO tbl_user_login (
            user_id, password, email, org_id, role_id, full_name, phone,
            is_demo, is_active, two_factor_enabled, legacy_uuid,
            created_at, updated_at
        )
        SELECT
            'usr_' || REPLACE(u.id::text, '-', ''),
            u.password_hash,
            u.email,
            u.org_id,
            u.role_id,
            u.full_name,
            u.phone,
            u.is_demo,
            u.is_active,
            FALSE,
            u.id,
            u.created_at,
            u.updated_at
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_user_login t WHERE t.legacy_uuid = u.id
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM tbl_user_login WHERE legacy_uuid IS NOT NULL")
