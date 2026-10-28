"""Add send-compliance columns to ``tbl_organizations``
(``tasks/automation-engine`` Step 13).

Five columns drive the Step-13 send-guard layer:

  * ``quiet_hours_start TIME DEFAULT '21:00:00'``
  * ``quiet_hours_end TIME DEFAULT '09:00:00'``
  * ``quiet_hours_timezone TEXT DEFAULT 'Asia/Kolkata'``
  * ``marketing_frequency_cap_per_week INT DEFAULT 3``
  * ``marketing_frequency_cap_enabled BOOL DEFAULT true``

Existing rows pick up the defaults atomically — no backfill UPDATE
needed. Operators tune via Settings → Send rules (Step-13 UI tab).

Also adds a partial index on ``tbl_automation_runs`` that powers
the hot-path frequency-cap query in
``automation/send_guard.check_frequency_cap`` — counts marketing
runs sent to a specific contact in the last 7 days. The partial
predicate (``status IN ('sent','dispatched')`` AND
``contact_id IS NOT NULL``) keeps the index narrow.

Chains after ``0133_seed_time_based_triggers``. Reversible.

Revision ID: 0134_org_compliance_settings
Revises: 0133_seed_time_based_triggers
Create Date: 2026-06-29 15:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0134_org_compliance_settings"
down_revision: Union[str, None] = "0133_seed_time_based_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "quiet_hours_start",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'21:00:00'"),
        ),
    )
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "quiet_hours_end",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'09:00:00'"),
        ),
    )
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "quiet_hours_timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Asia/Kolkata'"),
        ),
    )
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "marketing_frequency_cap_per_week",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "marketing_frequency_cap_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Frequency-cap hot-path index: counts marketing-category runs
    # sent to a specific contact in the last 7 days. Partial on
    # status + contact_id so the index stays narrow even on tenants
    # with millions of runs.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_automation_runs_contact_completed
            ON tbl_automation_runs (org_id, contact_id, completed_at DESC)
            WHERE contact_id IS NOT NULL
              AND status IN ('sent', 'dispatched')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_automation_runs_contact_completed")
    op.drop_column("tbl_organizations", "marketing_frequency_cap_enabled")
    op.drop_column("tbl_organizations", "marketing_frequency_cap_per_week")
    op.drop_column("tbl_organizations", "quiet_hours_timezone")
    op.drop_column("tbl_organizations", "quiet_hours_end")
    op.drop_column("tbl_organizations", "quiet_hours_start")
