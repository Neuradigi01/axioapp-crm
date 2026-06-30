"""workflow system_default flag

Step 21 of ``tasks/workflows/`` — adds the ``is_system_default``
boolean to ``tbl_workflows`` so the seeder can mark internal-only
default workflows (Lead Auto-Triage, Deal Won Slack Alert, Daily
Digest) that auto-activate per org and are protected from delete.

The flag is metadata only — RBAC + status state-machine + every
other gate keeps working unchanged. The service layer reads the flag
to refuse archive on system-default rows so an operator can't
accidentally disable the CRM's day-one safety nets.

Reversible. Downgrade drops the column.

Revision ID: 0146_workflow_system_default
Revises: 0145_seq_to_workflows
Create Date: 2026-06-30 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0146_workflow_system_default"
down_revision: Union[str, None] = "0145_seq_to_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "is_system_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_workflows", "is_system_default")
