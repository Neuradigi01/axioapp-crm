"""calls_created_by — track who logged each call.

Adds a nullable ``created_by_id`` UUID column to ``tbl_calls`` so the
Call Logs table can render "Logged by <rep>" alongside each row. No FK
because ``tbl_calls.assigned_to_id`` is already plain UUID and users
live in a different table hierarchy — org membership guarantees the
join safety at the service layer.

Existing rows are left with ``created_by_id=NULL`` — historical calls
predate this tracking and the column stays nullable forever so future
system-generated calls (webhook ingest, automation) can also skip it.

Revision ID: 0222_calls_created_by
Revises: 0221_bf_task_delete_perm
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0222_calls_created_by"
down_revision: Union[str, None] = "0221_bf_task_delete_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_calls",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_calls", "created_by_id")
