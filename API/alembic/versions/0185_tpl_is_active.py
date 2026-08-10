"""Add ``is_active`` toggle to ``tbl_message_templates``.

Owner / Admin (or any role granted ``templates.activate``) can flip
a template inactive to keep the row in the library for audit while
blocking every send path from picking it up. Campaigns, workflows,
automations, and the conversations composer all filter inactive
rows out server-side + hide them in their pickers.

Default ``true`` for existing rows so nothing observable changes on
migration — operators only see any effect after they explicitly
deactivate a template.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0185_tpl_is_active"
down_revision: str | None = "0184_appt_reminder_offsets"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_message_templates",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    # Partial index on the inactive flag — most rows are active, so the
    # filter narrows to a small subset when a picker runs
    # ``WHERE is_active = true``. Cheap to maintain, cheap to query.
    op.create_index(
        "ix_message_templates_org_active",
        "tbl_message_templates",
        ["org_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_templates_org_active", table_name="tbl_message_templates")
    op.drop_column("tbl_message_templates", "is_active")
