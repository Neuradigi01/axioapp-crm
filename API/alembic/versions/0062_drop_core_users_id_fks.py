"""Drop remaining core-CRM FKs that point at the legacy `users.id`.

Completes the soak cleanup started by `0037_drop_users_id_fks`
(2026-05-18). After DR.6/DR.7, nothing writes to the legacy `users`
table — auth and user data live in `tbl_user_login` +
`tbl_user_info` + `tbl_organization_members`. The 17 FK constraints
dropped here are zombie pointers: any user created after the DR.6.2
backfill is absent from `users`, so writes to these tables would
fail with `ForeignKeyViolationError`.

Application-level membership validation
(`_assert_user_in_org` in `core/leads/service.py`,
`core/contacts/service.py`, etc.) already runs before every
assignment write and is the new authoritative check.

Scope: core CRM only. Furniture-pack FKs (inventory.created_by_id,
custom_orders.assigned_to_id, custom_orders.created_by_id) are
NOT touched here — they belong to a separate pack-side migration.

`ondelete` semantics that previously rode on the FK are now the
offboarding flow's responsibility (see
`tasks/update-staff-offboarding/`).

Revision ID: 0062_drop_core_users_id_fks
Revises: 0061_whatsapp_account_config
Create Date: 2026-05-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0062_drop_core_users_id_fks"
down_revision: Union[str, None] = "0061_whatsapp_account_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, constraint_name, ondelete) — one entry per FK.
# Order is irrelevant for the drop; we preserve it for the recreate
# in downgrade() so the constraints come back identically.
_FKS: list[tuple[str, str, str, str]] = [
    ("activities", "user_id", "activities_user_id_fkey", "SET NULL"),
    ("appointments", "assigned_to_id", "appointments_assigned_to_id_fkey", "RESTRICT"),
    ("attendance", "user_id", "attendance_user_id_fkey", "CASCADE"),
    ("calls", "assigned_to_id", "calls_assigned_to_id_fkey", "SET NULL"),
    ("campaigns", "created_by_id", "campaigns_created_by_id_fkey", "SET NULL"),
    ("contacts", "assigned_to_id", "contacts_assigned_to_id_fkey", "SET NULL"),
    ("conversations", "assigned_to_id", "conversations_assigned_to_id_fkey", "SET NULL"),
    ("demo_credentials", "user_id", "demo_credentials_user_id_fkey", "CASCADE"),
    ("leads", "assigned_to_id", "leads_assigned_to_id_fkey", "SET NULL"),
    ("messages", "sender_user_id", "messages_sender_user_id_fkey", "SET NULL"),
    ("notifications", "user_id", "notifications_user_id_fkey", "CASCADE"),
    (
        "notification_preferences",
        "user_id",
        "notification_preferences_user_id_fkey",
        "CASCADE",
    ),
    ("reviews", "replied_by_id", "reviews_replied_by_id_fkey", "SET NULL"),
    ("staff_profiles", "user_id", "staff_profiles_user_id_fkey", "CASCADE"),
    ("staff_sessions", "user_id", "staff_sessions_user_id_fkey", "CASCADE"),
    ("tasks", "assigned_to_id", "tasks_assigned_to_id_fkey", "RESTRICT"),
    ("walk_ins", "assigned_to_id", "walk_ins_assigned_to_id_fkey", "SET NULL"),
]


def upgrade() -> None:
    for table, _column, constraint, _ondelete in _FKS:
        # IF EXISTS so a re-run (or a partial state where some
        # constraints were dropped manually) won't blow up.
        op.execute(
            f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{constraint}"'
        )


def downgrade() -> None:
    for table, column, constraint, ondelete in _FKS:
        op.create_foreign_key(
            constraint,
            table,
            "users",
            [column],
            ["id"],
            ondelete=ondelete,
        )
