"""Chatbots foundation — five tables + enums + RLS
(``tasks/chatbot-builder`` Step 1).

Separate module from ``core/workflows/`` per manager spec 2026-08-13.
Where workflows fire on internal CRM events, chatbots fire on inbound
customer messages and drive a conversational flow with buttons,
questions, and branching.

Five tables land here:

  * ``tbl_chatbots`` — bot definition (name, status, ``trigger_config``
    JSONB, ``graph`` JSONB). One trigger per bot per Decision §3.
  * ``tbl_chatbot_runs`` — one row per inbound-message-driven
    enrolment on a conversation.
  * ``tbl_chatbot_step_runs`` — append-only per-node audit log for
    the diagnostics UI.
  * ``tbl_chatbot_meters`` — per-conversation-per-bot AND per-org
    daily reply counters for the runaway guard (Decision §9).
  * ``tbl_chatbot_pending_replies`` — signed-email-reply-URL nonce
    store (Step 11).

Five ENUMs back the status fields:

  * ``chatbot_status`` (draft / live / paused / archived)
  * ``chatbot_run_status`` (running / parked / completed / canceled /
    errored)
  * ``chatbot_step_status`` (pending / running / completed / skipped /
    errored)
  * ``chatbot_trigger_mode`` (any / keyword / regex)
  * ``chatbot_trigger_channel`` (any / whatsapp / email)

Two column additions on existing tables:

  * ``tbl_messages.chatbot_run_id`` — nullable FK to
    ``tbl_chatbot_runs``. Populated on bot-authored outbounds; drives
    the human-takeover detection in Step 6 (a NULL value means "a
    real user sent this").
  * ``tbl_contacts.is_placeholder`` — flags contacts auto-created
    from unknown inbound WhatsApp numbers. Nightly sweeper deletes
    stale placeholders (Case #23).

RLS policies match every other tenant-scoped table in the build —
``org_id = current_setting('app.current_org_id')`` gate.

Chains after ``0188_bf_task_assign_perm``. Reversible (FK-safe drop
order on downgrade).

Revision ID: 0189_chatbots_init
Revises:     0188_bf_task_assign_perm
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0189_chatbots_init"
down_revision: str | None = "0188_bf_task_assign_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- ENUMs ----------------------------------------------------------------
    chatbot_status = postgresql.ENUM(
        "draft",
        "live",
        "paused",
        "archived",
        name="chatbot_status",
        create_type=True,
    )
    chatbot_status.create(bind, checkfirst=True)

    chatbot_run_status = postgresql.ENUM(
        "running",
        "parked",
        "completed",
        "canceled",
        "errored",
        name="chatbot_run_status",
        create_type=True,
    )
    chatbot_run_status.create(bind, checkfirst=True)

    chatbot_step_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "skipped",
        "errored",
        name="chatbot_step_status",
        create_type=True,
    )
    chatbot_step_status.create(bind, checkfirst=True)

    chatbot_trigger_mode = postgresql.ENUM(
        "any",
        "keyword",
        "regex",
        name="chatbot_trigger_mode",
        create_type=True,
    )
    chatbot_trigger_mode.create(bind, checkfirst=True)

    chatbot_trigger_channel = postgresql.ENUM(
        "any",
        "whatsapp",
        "email",
        name="chatbot_trigger_channel",
        create_type=True,
    )
    chatbot_trigger_channel.create(bind, checkfirst=True)

    # --- tbl_chatbots ---------------------------------------------------------
    op.create_table(
        "tbl_chatbots",
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'Custom'"),
        ),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="chatbot_status", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                "'{\"channel\": \"any\", \"mode\": \"any\", \"keywords\": [], "
                "\"regex_pattern\": null, \"case_sensitive\": false, "
                "\"first_message_only\": false}'::jsonb"
            ),
        ),
        sa.Column(
            "graph",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{\"nodes\": [], \"edges\": []}'::jsonb"),
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
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
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chatbots_org_lower_name
            ON tbl_chatbots (org_id, lower(name))
        """
    )
    op.create_index(
        "ix_chatbots_org_status",
        "tbl_chatbots",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_chatbots_org_priority_created",
        "tbl_chatbots",
        ["org_id", "priority", "created_at"],
    )

    # --- tbl_chatbot_runs -----------------------------------------------------
    op.create_table(
        "tbl_chatbot_runs",
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
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chatbot_version", sa.Integer(), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # lead_id — no FK on the definition-level table since leads may
        # not yet exist for a run (bot creates the lead later via
        # create_lead node). Kept unconstrained for that flexibility.
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="chatbot_run_status", create_type=False),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("current_node_id", sa.Text(), nullable=True),
        sa.Column(
            "next_step_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "is_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("canceled_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chatbot_runs_bot_conv_status",
        "tbl_chatbot_runs",
        ["org_id", "chatbot_id", "conversation_id", "status"],
    )
    # Hot path — sweeper looks up parked runs per conversation on every
    # inbound message. Partial index keeps it tiny.
    op.execute(
        """
        CREATE INDEX ix_chatbot_runs_conv_parked
            ON tbl_chatbot_runs (conversation_id, status)
            WHERE status = 'parked'
        """
    )
    op.create_index(
        "ix_chatbot_runs_org_started",
        "tbl_chatbot_runs",
        ["org_id", sa.text("started_at DESC")],
    )
    # Test-fire runs auto-swept after 24h — index for that sweeper.
    op.execute(
        """
        CREATE INDEX ix_chatbot_runs_test_sweep
            ON tbl_chatbot_runs (started_at)
            WHERE is_test = true
        """
    )

    # --- tbl_chatbot_step_runs ------------------------------------------------
    op.create_table(
        "tbl_chatbot_step_runs",
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
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbot_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="chatbot_step_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("output_edge_label", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chatbot_step_runs_run_started",
        "tbl_chatbot_step_runs",
        ["run_id", "started_at"],
    )
    op.execute(
        """
        CREATE INDEX ix_chatbot_step_runs_org_errored
            ON tbl_chatbot_step_runs (org_id, started_at DESC)
            WHERE status = 'errored'
        """
    )

    # --- tbl_chatbot_meters ---------------------------------------------------
    op.create_table(
        "tbl_chatbot_meters",
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
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "window_start",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Two partial uniques — one per shape (per-conversation vs per-org
    # global). Postgres treats NULLs as distinct by default so this
    # split is required to keep both shapes correct without
    # NULLS NOT DISTINCT gymnastics.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chatbot_meters_bot_conv
            ON tbl_chatbot_meters (org_id, bot_id, conversation_id)
            WHERE bot_id IS NOT NULL AND conversation_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chatbot_meters_org_global
            ON tbl_chatbot_meters (org_id)
            WHERE bot_id IS NULL AND conversation_id IS NULL
        """
    )

    # --- tbl_chatbot_pending_replies ------------------------------------------
    op.create_table(
        "tbl_chatbot_pending_replies",
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
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbot_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("button_id", sa.String(128), nullable=False),
        sa.Column("button_label", sa.String(255), nullable=False),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "nonce",
            name="uq_chatbot_pending_replies_nonce",
        ),
    )
    op.create_index(
        "ix_chatbot_pending_replies_expiry",
        "tbl_chatbot_pending_replies",
        ["expires_at"],
    )

    # --- ALTER TABLE: existing tables get new columns -------------------------
    op.add_column(
        "tbl_messages",
        sa.Column(
            "chatbot_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbot_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Partial index — most messages are human-sent, so index only the
    # bot rows so the human-takeover query (WHERE chatbot_run_id IS
    # NULL) is fast and the bot-attribution query (WHERE chatbot_run_id
    # IS NOT NULL) hits an index.
    op.execute(
        """
        CREATE INDEX ix_messages_chatbot_run
            ON tbl_messages (chatbot_run_id)
            WHERE chatbot_run_id IS NOT NULL
        """
    )

    op.add_column(
        "tbl_contacts",
        sa.Column(
            "is_placeholder",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Partial index — placeholders are the minority, so this stays
    # small; the nightly sweeper (Case #23) scans only this subset.
    op.execute(
        """
        CREATE INDEX ix_contacts_placeholder
            ON tbl_contacts (org_id, created_at)
            WHERE is_placeholder = true
        """
    )

    # --- RLS policies ---------------------------------------------------------
    for table in (
        "tbl_chatbots",
        "tbl_chatbot_runs",
        "tbl_chatbot_step_runs",
        "tbl_chatbot_meters",
        "tbl_chatbot_pending_replies",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )


def downgrade() -> None:
    # Drop policies + tables in FK-safe reverse order. Indexes drop
    # with their tables. Partial indexes on tbl_messages and
    # tbl_contacts are dropped before the column drops (implicit).

    for table in (
        "tbl_chatbot_pending_replies",
        "tbl_chatbot_meters",
        "tbl_chatbot_step_runs",
        "tbl_chatbot_runs",
        "tbl_chatbots",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    # Existing-table column reversals first — clears the FK from
    # tbl_messages before we drop tbl_chatbot_runs.
    op.execute("DROP INDEX IF EXISTS ix_contacts_placeholder")
    op.drop_column("tbl_contacts", "is_placeholder")

    op.execute("DROP INDEX IF EXISTS ix_messages_chatbot_run")
    op.drop_column("tbl_messages", "chatbot_run_id")

    op.drop_table("tbl_chatbot_pending_replies")

    op.execute("DROP INDEX IF EXISTS uq_chatbot_meters_org_global")
    op.execute("DROP INDEX IF EXISTS uq_chatbot_meters_bot_conv")
    op.drop_table("tbl_chatbot_meters")

    op.execute("DROP INDEX IF EXISTS ix_chatbot_step_runs_org_errored")
    op.drop_table("tbl_chatbot_step_runs")

    op.execute("DROP INDEX IF EXISTS ix_chatbot_runs_test_sweep")
    op.execute("DROP INDEX IF EXISTS ix_chatbot_runs_conv_parked")
    op.drop_table("tbl_chatbot_runs")

    op.execute("DROP INDEX IF EXISTS uq_chatbots_org_lower_name")
    op.drop_table("tbl_chatbots")

    for enum_name in (
        "chatbot_trigger_channel",
        "chatbot_trigger_mode",
        "chatbot_step_status",
        "chatbot_run_status",
        "chatbot_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
