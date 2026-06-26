"""automation engine: triggers + runs tables + RLS

Step 1 of ``tasks/automation-engine/`` lands the two tables that back
Module B (the single-event trigger engine):

  ``tbl_automation_triggers``
    One row per operator-configured automation rule. Shape mirrors
    the manager spec — id, org_id, name, enabled, event_type,
    conditions JSONB, channel + template_id (FK
    ``tbl_message_templates`` from Module A), delay_seconds,
    recipient_resolver + config, audit columns.

  ``tbl_automation_runs``
    One row per trigger firing — the audit + run-history table. A
    fresh run lands in ``status='queued'``, the Celery dispatcher
    flips it to ``dispatched`` when it pulls it off the queue, then
    ``sent`` / ``failed`` / ``skipped`` after the channel adapter
    returns. ``channel_message_id`` carries the adapter's id so the
    inbox can later correlate inbound replies.

One new Postgres enum ``automation_run_status``.

RLS-enabled + forced on both tables; tenant-isolation policies
keyed on ``app.org_id`` GUC (same pattern every Module A table uses).
Hot-path indexes for the matcher (``org_id, event_type, enabled``),
the run-history view (``trigger_id, scheduled_at DESC``), and the
dispatcher sweep (``org_id, status, scheduled_at WHERE status IN
('queued','dispatched')``).

Reversible — downgrade drops both tables + the enum cleanly.

Revision ID: 0126_automation_schema
Revises: 0125_review_external_sync
Create Date: 2026-06-26 02:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0126_automation_schema"
down_revision: Union[str, None] = "0125_review_external_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RUN_STATUS_VALUES = ("queued", "dispatched", "sent", "failed", "skipped")


def upgrade() -> None:
    run_status_enum = postgresql.ENUM(
        *_RUN_STATUS_VALUES, name="automation_run_status"
    )
    run_status_enum.create(op.get_bind(), checkfirst=True)

    # --- tbl_automation_triggers --------------------------------------

    op.create_table(
        "tbl_automation_triggers",
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
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(
                name="conversation_channel",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_message_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "delay_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "recipient_resolver",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'contact.email'"),
        ),
        sa.Column(
            "recipient_resolver_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_automation_triggers_org_event_enabled",
        "tbl_automation_triggers",
        ["org_id", "event_type", "enabled"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_automation_triggers_org_lower_name "
        "ON tbl_automation_triggers (org_id, lower(name))"
    )

    op.execute(
        "ALTER TABLE tbl_automation_triggers ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE tbl_automation_triggers FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_automation_triggers
            ON tbl_automation_triggers
            USING (org_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
        """
    )

    # --- tbl_automation_runs ------------------------------------------

    op.create_table(
        "tbl_automation_runs",
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
            "trigger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_automation_triggers.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "event_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_RUN_STATUS_VALUES,
                name="automation_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("channel_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_automation_runs_trigger_scheduled_desc",
        "tbl_automation_runs",
        ["trigger_id", sa.text("scheduled_at DESC")],
    )
    op.execute(
        "CREATE INDEX ix_automation_runs_org_status_scheduled "
        "ON tbl_automation_runs (org_id, status, scheduled_at) "
        "WHERE status IN ('queued', 'dispatched')"
    )

    op.execute("ALTER TABLE tbl_automation_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tbl_automation_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_automation_runs
            ON tbl_automation_runs
            USING (org_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_automation_runs "
        "ON tbl_automation_runs"
    )
    op.execute("DROP INDEX IF EXISTS ix_automation_runs_org_status_scheduled")
    op.drop_index(
        "ix_automation_runs_trigger_scheduled_desc",
        table_name="tbl_automation_runs",
    )
    op.drop_table("tbl_automation_runs")

    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_automation_triggers "
        "ON tbl_automation_triggers"
    )
    op.execute("DROP INDEX IF EXISTS uq_automation_triggers_org_lower_name")
    op.drop_index(
        "ix_automation_triggers_org_event_enabled",
        table_name="tbl_automation_triggers",
    )
    op.drop_table("tbl_automation_triggers")

    sa.Enum(name="automation_run_status").drop(
        op.get_bind(), checkfirst=True
    )
