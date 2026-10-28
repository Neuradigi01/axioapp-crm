"""tbl_whatsapp_assignment_rules
(whatsapp-platform-upgrade Step 18).

One RLS-scoped table that backs the auto-assignment engine. Each
row carries a `strategy` enum + a `config` JSONB whose shape depends
on the strategy:

  * ``round_robin``   — ``{"eligible_user_ids": [<uuid>, ...]}``
  * ``load_balanced`` — ``{"eligible_user_ids": [...], "cap_per_user": <int|null>}``
  * ``tag_based``     — ``{"mapping": {"<tag_id>": "<user_id>", ...}}``
  * ``team_based``    — ``{"team_id": "<uuid>"}`` (falls back to
                         ``eligible_user_ids`` if the teams module
                         isn't installed)

``last_assigned_user_id`` is the round-robin state — the engine picks
the user immediately after this one in the eligible list on each
new assignment, then writes the choice back here under a
``SELECT ... FOR UPDATE`` lock so concurrent webhooks don't
double-assign.

``skip_outside_hours`` opts the rule into Step-11's business-hours
schedule — when on, the rule sits out outside the configured window
and leaves the conversation unassigned (the operator picks it up
manually when they're back).

Index on ``(org_id, enabled, priority, created_at)`` for the
evaluation path — same pattern as the keyword rules.

Chains after ``0105_backfill_auto_perm``.

Revision ID: 0106_assignment_rules
Revises: 0105_backfill_auto_perm
Create Date: 2026-06-23 00:06:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0106_assignment_rules"
down_revision: Union[str, None] = "0105_backfill_auto_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STRATEGY_ENUM = "whatsapp_assignment_strategy"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TYPE {_STRATEGY_ENUM} AS ENUM (
            'round_robin', 'load_balanced', 'tag_based', 'team_based'
        )
        """
    )
    op.create_table(
        "tbl_whatsapp_assignment_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "strategy",
            postgresql.ENUM(
                "round_robin",
                "load_balanced",
                "tag_based",
                "team_based",
                name=_STRATEGY_ENUM,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "skip_outside_hours",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "last_assigned_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
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
        "ix_assignment_rules_org_enabled_priority",
        "tbl_whatsapp_assignment_rules",
        ["org_id", "enabled", "priority", "created_at"],
    )
    op.execute(
        "ALTER TABLE tbl_whatsapp_assignment_rules "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_assignment_rules
        ON tbl_whatsapp_assignment_rules
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_assignment_rules "
        "ON tbl_whatsapp_assignment_rules"
    )
    op.drop_index(
        "ix_assignment_rules_org_enabled_priority",
        table_name="tbl_whatsapp_assignment_rules",
    )
    op.drop_table("tbl_whatsapp_assignment_rules")
    op.execute(f"DROP TYPE {_STRATEGY_ENUM}")
