"""Deliverability surface: bounce events + suppression list +
engagement timestamps (``tasks/automation-engine`` Step 14).

Three concerns in one migration:

  1. ``tbl_email_bounce_events`` — append-only audit log of every
     bounce / complaint / unsubscribe webhook the CRM receives
     from a configured email provider (Mailgun / SendGrid / SES /
     Postmark). ``provider_event_id`` is unique across the table
     so provider re-deliveries don't duplicate rows.
  2. ``tbl_automation_suppressions`` — one row per
     ``(org_id, channel, address)`` the send-guard must refuse.
     Populated by the bounce handler + the operator's manual
     "Add to suppression list" action.
  3. ``tbl_automation_runs`` gains ``opened_at`` + ``clicked_at``
     columns so the open-pixel + click-redirect endpoints can
     surface engagement on the per-contact timeline.

RLS policies on the two new tables match every other tenant-scoped
table in the build — ``org_id = current_setting('app.current_org_id')``
gate.

Chains after ``0134_org_compliance_settings``. Reversible.

Revision ID: 0135_deliverability_tables
Revises: 0134_org_compliance_settings
Create Date: 2026-06-29 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0135_deliverability_tables"
down_revision: Union[str, None] = "0134_org_compliance_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) New ENUM type for the suppression reason. ``conversation_channel``
    #    already exists from earlier migrations — reuse without
    #    creating a duplicate.
    suppression_reason = postgresql.ENUM(
        "hard_bounce",
        "complaint",
        "unsubscribe",
        "manual",
        name="automation_suppression_reason",
        create_type=True,
    )
    suppression_reason.create(op.get_bind(), checkfirst=True)

    # 2) tbl_email_bounce_events — append-only webhook audit log.
    op.create_table(
        "tbl_email_bounce_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("email_address", sa.Text(), nullable=False),
        sa.Column("bounce_type", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=False),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_email_bounce_events_org_address",
        "tbl_email_bounce_events",
        ["org_id", "email_address"],
    )
    op.create_index(
        "uq_email_bounce_events_provider_event_id",
        "tbl_email_bounce_events",
        ["provider_event_id"],
        unique=True,
    )

    # 3) tbl_automation_suppressions — the send-guard's blocklist.
    op.create_table(
        "tbl_automation_suppressions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(
                name="conversation_channel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(
                name="automation_suppression_reason",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_automation_suppressions_org_channel_address",
        "tbl_automation_suppressions",
        ["org_id", "channel", "address"],
        unique=True,
    )

    # 4) RLS policies on the two new tables. Match the
    #    ``current_setting`` gate every other tenant-scoped table uses.
    for table in ("tbl_email_bounce_events", "tbl_automation_suppressions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )

    # 5) Engagement columns on tbl_automation_runs.
    op.add_column(
        "tbl_automation_runs",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_automation_runs",
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_automation_runs", "clicked_at")
    op.drop_column("tbl_automation_runs", "opened_at")

    op.execute(
        "DROP POLICY IF EXISTS tbl_automation_suppressions_tenant_isolation "
        "ON tbl_automation_suppressions"
    )
    op.execute(
        "DROP POLICY IF EXISTS tbl_email_bounce_events_tenant_isolation "
        "ON tbl_email_bounce_events"
    )
    op.drop_index(
        "uq_automation_suppressions_org_channel_address",
        table_name="tbl_automation_suppressions",
    )
    op.drop_table("tbl_automation_suppressions")
    op.drop_index(
        "uq_email_bounce_events_provider_event_id",
        table_name="tbl_email_bounce_events",
    )
    op.drop_index(
        "ix_email_bounce_events_org_address",
        table_name="tbl_email_bounce_events",
    )
    op.drop_table("tbl_email_bounce_events")

    op.execute("DROP TYPE IF EXISTS automation_suppression_reason")
