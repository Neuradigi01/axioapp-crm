"""tasks

Creates the `tasks` table (tenant-scoped, RLS-on) plus the
`task_status` and `task_priority` Postgres ENUMs and the two hot-path
read indexes:

- ``ix_tasks_my_open`` — covers `GET /tasks/me?status=open` ordered by
  due_at: ``(org_id, assigned_to_id, status, due_at)``.
- ``ix_tasks_related`` — covers per-entity panels: ``(org_id,
  related_entity_type, related_entity_id)``.

Revision ID: 0009_tasks
Revises: 0008_activities
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0009_tasks"
down_revision: Union[str, None] = "0008_activities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TASK_STATUS_VALUES = ("open", "done", "cancelled")
_TASK_PRIORITY_VALUES = ("low", "med", "high")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_TASK_STATUS_VALUES, name="task_status", create_type=False
    )
    priority_enum = postgresql.ENUM(
        *_TASK_PRIORITY_VALUES, name="task_priority", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)
    priority_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=False),
        sa.Column("related_entity_type", sa.String(length=64), nullable=True),
        sa.Column("related_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            priority_enum,
            server_default=sa.text("'med'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_tasks_org_id", "tasks", ["org_id"])
    op.create_index("ix_tasks_assigned_to_id", "tasks", ["assigned_to_id"])
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"])
    op.create_index(
        "ix_tasks_my_open",
        "tasks",
        ["org_id", "assigned_to_id", "status", "due_at"],
    )
    op.create_index(
        "ix_tasks_related",
        "tasks",
        ["org_id", "related_entity_type", "related_entity_id"],
    )

    apply_rls("tasks")


def downgrade() -> None:
    drop_rls("tasks")
    op.drop_index("ix_tasks_related", table_name="tasks")
    op.drop_index("ix_tasks_my_open", table_name="tasks")
    op.drop_index("ix_tasks_due_at", table_name="tasks")
    op.drop_index("ix_tasks_assigned_to_id", table_name="tasks")
    op.drop_index("ix_tasks_org_id", table_name="tasks")
    op.drop_table("tasks")
    postgresql.ENUM(name="task_priority").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="task_status").drop(op.get_bind(), checkfirst=True)
