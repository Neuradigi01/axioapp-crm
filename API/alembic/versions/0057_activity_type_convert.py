"""activities: add 'convert' to activity_type ENUM

The walk-in → lead conversion flow (and the deferred leads →
opportunity flow) writes a dedicated audit activity for every
conversion so the entity's timeline shows
*"Asha was converted to lead <id>."*

Same pattern as `0053_activity_type_reassign`. Wrapped in an
`autocommit_block` because `ALTER TYPE ... ADD VALUE` cannot run
inside a transaction.

`IF NOT EXISTS` (PG 9.6+) makes the upgrade idempotent. Downgrade is
a no-op — Postgres can't drop an enum value safely (would require
recreating the type + swapping every reference). Existing rows
remain valid post-downgrade; the Python `ActivityType.convert`
member just stops being produced by app code.

Revision ID: 0057_activity_type_convert
Revises: 0056_walkins_linked_lead_id
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0057_activity_type_convert"
down_revision: Union[str, None] = "0056_walkins_linked_lead_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'convert'"
        )


def downgrade() -> None:
    pass
