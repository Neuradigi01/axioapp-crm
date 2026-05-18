"""Drop FKs on auth_sessions.user_id and audit_logs.user_id

Partial cut of the soak checklist (see
`tasks/phase-4.5-demo-roles-setup/README.md`).

After DR.6/7, the UUID identity is `tbl_user_login.legacy_uuid`; the
legacy `users` table is on soak and only carries the 11 rows
migrated from before DR.6. Step 2.5.6 (the invite-user flow) creates
brand-new users whose `legacy_uuid` is NOT in `users` — they'd
violate the existing FKs that target `users.id`. The proper fix is to
retarget these FKs to `tbl_user_login(legacy_uuid)` once the soak
ends and `users` can be dropped. For now we drop the FK constraints
but keep the UUID columns + their indexes so the join semantics still
work at the application layer.

Affects:
  - `auth_sessions.user_id`  → drop FK (column stays, RLS unchanged)
  - `audit_logs.user_id`     → drop FK (column stays, RLS unchanged)

The other FKs pointing at `users.id` (`staff_sessions.user_id`,
`staff_profiles.user_id`, `demo_credentials.user_id`) are NOT touched
here — they're only exercised by code paths that still operate on
pre-soak rows.

Revision ID: 0037_drop_users_id_fks
Revises: 0036_invitations
Create Date: 2026-05-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0037_drop_users_id_fks"
down_revision: Union[str, None] = "0036_invitations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "auth_sessions_user_id_fkey", "auth_sessions", type_="foreignkey"
    )
    op.drop_constraint(
        "audit_logs_user_id_fkey", "audit_logs", type_="foreignkey"
    )


def downgrade() -> None:
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "auth_sessions_user_id_fkey",
        "auth_sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
