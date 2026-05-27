"""activities: add 'reassign' to activity_type ENUM

The cross-CRM transfer feature (single + bulk reassign of contacts /
leads / walk-ins / appointments / tasks) writes a dedicated audit
activity for every transfer so the entity's timeline shows
*"X reassigned this from A to B."*

Adds a new enum value `reassign` alongside the existing
`note / call / email / whatsapp / status_change / task`. The timeline
UI renders it with its own icon distinct from `status_change`.

`ALTER TYPE ... ADD VALUE IF NOT EXISTS` is idempotent in PG 9.6+, so
re-running the migration is safe. Wrapped in an `autocommit_block`
because the ALTER TYPE statement cannot run inside a transaction.

The downgrade is a **no-op** — Postgres does not support
`ALTER TYPE ... DROP VALUE`. Removing the value would require
recreating the type, copying every row referencing it, and swapping
the table column over. That's a high-risk dance for a never-needed
operation; instead, the downgrade leaves the value defined but
no longer reachable in the Python enum.

Revision ID: 0053_activity_type_reassign
Revises: 0052_contacts_owner_last_act
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0053_activity_type_reassign"
down_revision: Union[str, None] = "0052_contacts_owner_last_act"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'reassign'"
        )


def downgrade() -> None:
    # See module docstring — Postgres can't drop an enum value safely.
    # The Python `ActivityType.reassign` member will simply not be
    # produced by app code post-downgrade; existing rows remain valid.
    pass
