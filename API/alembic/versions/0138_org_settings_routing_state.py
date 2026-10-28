"""Add ``routing_state`` JSONB column to ``tbl_org_settings``
(``tasks/workflows`` Step 9).

Per-pool round-robin pointer state for the workflow routing
action handlers. Keyed by ``pool_spec`` string (e.g.
``"role:Sales"``) → ``{"last_picked_user_id": "<uuid>",
"last_picked_at": "<iso>"}``. The Step-9 service-layer helper
mutates this under a ``SELECT ... FOR UPDATE`` row lock so two
concurrent workflow firings can't double-assign or skip a user.

Existing rows pick up the empty-dict default atomically. No
backfill needed.

Chains after ``0137_bf_workflows_perm``. Reversible.

Revision ID: 0138_org_settings_routing_state
Revises: 0137_bf_workflows_perm
Create Date: 2026-06-29 20:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0138_org_settings_routing_state"
down_revision: Union[str, None] = "0137_bf_workflows_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "routing_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_org_settings", "routing_state")
