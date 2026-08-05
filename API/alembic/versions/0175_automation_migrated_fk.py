"""tbl_automation_triggers.migrated_to_workflow_id — FK column for the
workflows-absorb-automation cutover (Step 1 of the track).

Adds a nullable UUID column pointing at ``tbl_workflows.id`` so the
data migration in ``0176_bf_autos_to_workflows`` can record the mapping
between each source automation and its single-step workflow mirror.
Redirects (``/user/automations/:id`` → ``/user/workflows/<mirror>``)
and the reversible downgrade both read this FK; the workflow-absorb
dispatcher guard (deferred to a future track) would gate the
automation matcher on ``migrated_to_workflow_id IS NULL``.

``ON DELETE SET NULL`` — deleting a mirror workflow unlinks the
source automation but does not cascade. The source row is soft-
disabled (``enabled = false``) at data-migration time; downgrade
restores the pre-migration ``enabled`` value.

Nullable + index-only — no default. Existing rows land with NULL
until the data-migration in ``0176_bf_autos_to_workflows`` populates
them.

Revision ID: 0175_automation_migrated_fk
Revises:     0174_consent_allow_delete
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0175_automation_migrated_fk"
down_revision: str | None = "0174_consent_allow_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_automation_triggers",
        sa.Column(
            "migrated_to_workflow_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_automation_triggers_migrated_workflow",
        source_table="tbl_automation_triggers",
        referent_table="tbl_workflows",
        local_cols=["migrated_to_workflow_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_automation_triggers_migrated_workflow_id",
        "tbl_automation_triggers",
        ["migrated_to_workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_triggers_migrated_workflow_id",
        table_name="tbl_automation_triggers",
    )
    op.drop_constraint(
        "fk_automation_triggers_migrated_workflow",
        "tbl_automation_triggers",
        type_="foreignkey",
    )
    op.drop_column("tbl_automation_triggers", "migrated_to_workflow_id")
