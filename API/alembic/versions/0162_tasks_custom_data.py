"""add tbl_tasks.custom_data JSONB (tasks review T4).

Extends ``tbl_tasks`` with a ``custom_data`` JSONB column defaulting
to an empty object, so ``entity_type='task'`` custom fields can flow
through the standard dynamic-form path (Rule 3 of the master prompt).

The existing custom-fields router already accepts ``entity_type=task``;
the missing piece was a column on Task to store the payload. This
migration closes that. Nullable = false + server default = ``'{}'``
so existing rows carry on unchanged.

Also adds a GIN index for future custom-field filter queries — matches
the pattern established on ``tbl_contacts.custom_data`` and
``tbl_leads.custom_data``.

Non-destructive on existing rows. Downgrade cleanly drops the index +
column.

Revision ID: 0162_tasks_custom_data
Revises:     0161_walkins_extra_fields
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0162_tasks_custom_data"
down_revision: Union[str, None] = "0161_walkins_extra_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_tasks",
        sa.Column(
            "custom_data",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_tbl_tasks_custom_data_gin",
        "tbl_tasks",
        ["custom_data"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_tasks_custom_data_gin", table_name="tbl_tasks")
    op.drop_column("tbl_tasks", "custom_data")
