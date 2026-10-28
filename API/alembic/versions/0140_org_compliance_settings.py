"""Add compliance-gate columns to ``tbl_org_settings``
(``tasks/workflows`` Step 12).

Nine new columns drive the Step-12 send-compliance layer:

  * ``quiet_hours_enabled``                    BOOL DEFAULT TRUE
  * ``quiet_hours_start``                      TIME DEFAULT '21:00:00'
  * ``quiet_hours_end``                        TIME DEFAULT '09:00:00'
  * ``quiet_hours_timezone``                   TEXT DEFAULT 'Asia/Kolkata'
  * ``frequency_cap_marketing_per_week``       INT  DEFAULT 5
  * ``frequency_cap_marketing_per_day``        INT  DEFAULT 2
  * ``transactional_bypass_quiet_hours``       BOOL DEFAULT TRUE
  * ``transactional_bypass_frequency_cap``     BOOL DEFAULT TRUE
  * ``unsubscribe_link_required_in_marketing_email`` BOOL DEFAULT TRUE

Existing rows pick up the defaults atomically. No backfill needed.

Note: there's a similar-purpose column set on ``tbl_organizations``
from the automation-engine track (migration 0134) — those drive
``core/automation/send_guard.py`` for the automation engine's
single-event triggers. The Step-12 spec puts the workflows
compliance layer on ``tbl_org_settings`` so it composes with the
Settings → General page; a future track unifies the two sources of
truth.

Chains after ``0139_workflow_event_waits``. Reversible.

Revision ID: 0140_org_compliance_settings
Revises: 0139_workflow_event_waits
Create Date: 2026-06-29 22:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0140_org_compliance_settings"
down_revision: Union[str, None] = "0139_workflow_event_waits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "quiet_hours_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "quiet_hours_start",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'21:00:00'"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "quiet_hours_end",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'09:00:00'"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "quiet_hours_timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Asia/Kolkata'"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "frequency_cap_marketing_per_week",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "frequency_cap_marketing_per_day",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "transactional_bypass_quiet_hours",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "transactional_bypass_frequency_cap",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "unsubscribe_link_required_in_marketing_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "tbl_org_settings", "unsubscribe_link_required_in_marketing_email"
    )
    op.drop_column("tbl_org_settings", "transactional_bypass_frequency_cap")
    op.drop_column("tbl_org_settings", "transactional_bypass_quiet_hours")
    op.drop_column("tbl_org_settings", "frequency_cap_marketing_per_day")
    op.drop_column("tbl_org_settings", "frequency_cap_marketing_per_week")
    op.drop_column("tbl_org_settings", "quiet_hours_timezone")
    op.drop_column("tbl_org_settings", "quiet_hours_end")
    op.drop_column("tbl_org_settings", "quiet_hours_start")
    op.drop_column("tbl_org_settings", "quiet_hours_enabled")
