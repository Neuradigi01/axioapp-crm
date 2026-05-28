"""Drop remaining furniture-pack FKs that point at the legacy `users.id`.

Pack-side companion to `0062_drop_core_users_id_fks` (DR.6.7).
Same rationale: after DR.6/DR.7 nothing writes to the legacy `users`
table, so these FKs are zombie pointers that break for any user
created post-soak.

Kept as a separate revision (instead of bundled into 0062) so that
rolling the pack cleanup back never disturbs core CRM schema.

Application-level membership validation remains the authoritative
check — the pack reassign service functions mirror the core
`_assert_user_in_org` pattern.

Revision ID: 0063_drop_pack_users_id_fks
Revises: 0062_drop_core_users_id_fks
Create Date: 2026-05-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0063_drop_pack_users_id_fks"
down_revision: Union[str, None] = "0062_drop_core_users_id_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FKS: list[tuple[str, str, str, str]] = [
    (
        "fp_inventory_movements",
        "user_id",
        "fp_inventory_movements_user_id_fkey",
        "SET NULL",
    ),
    (
        "fp_custom_orders",
        "assigned_to_id",
        "fp_custom_orders_assigned_to_id_fkey",
        "SET NULL",
    ),
    (
        "fp_custom_order_stages",
        "user_id",
        "fp_custom_order_stages_user_id_fkey",
        "SET NULL",
    ),
]


def upgrade() -> None:
    for table, _column, constraint, _ondelete in _FKS:
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
