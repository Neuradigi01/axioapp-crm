"""Keyword-rule engine tables
(whatsapp-platform-upgrade Step 17).

Two RLS-scoped tables that back the per-inbound rule engine:

  * ``tbl_whatsapp_keyword_rules`` — one row per rule. ``keywords``
    is a text array; the match-type enum decides how each entry is
    tested against the inbound text. ``priority`` is the primary
    sort key — lower = evaluated first. ``enabled=false`` rows are
    skipped at evaluation time without dropping the row.

  * ``tbl_whatsapp_keyword_actions`` — ordered list of actions per
    rule. ``action_type`` is an enum, ``action_config`` carries the
    type-specific payload (template id, user id, tag id, text body,
    etc.). ``position`` orders actions within a rule.

Both tables CASCADE on ``rule_id`` so deleting a rule cleans up its
actions atomically.

Chains after ``0103_auto_reply_settings``.

Revision ID: 0104_keyword_rules
Revises: 0103_auto_reply_settings
Create Date: 2026-06-23 00:04:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0104_keyword_rules"
down_revision: Union[str, None] = "0103_auto_reply_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MATCH_TYPE_ENUM = "whatsapp_keyword_match_type"
_ACTION_TYPE_ENUM = "whatsapp_keyword_action_type"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TYPE {_MATCH_TYPE_ENUM} AS ENUM (
            'contains', 'exact', 'regex'
        )
        """
    )
    op.execute(
        f"""
        CREATE TYPE {_ACTION_TYPE_ENUM} AS ENUM (
            'reply_text',
            'reply_template',
            'tag_conversation',
            'assign_to_user',
            'escalate_to_ai'
        )
        """
    )

    # ----- tbl_whatsapp_keyword_rules ------------------------------
    op.create_table(
        "tbl_whatsapp_keyword_rules",
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
            "keywords",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "match_type",
            postgresql.ENUM(
                "contains",
                "exact",
                "regex",
                name=_MATCH_TYPE_ENUM,
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text(f"'contains'::{_MATCH_TYPE_ENUM}"),
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
    # Evaluation-path index: enabled rules sorted by priority asc, then
    # created_at asc for stable tiebreak. Operators with hundreds of
    # rules get O(log n) lookup instead of a sequential scan.
    op.create_index(
        "ix_keyword_rules_org_enabled_priority",
        "tbl_whatsapp_keyword_rules",
        ["org_id", "enabled", "priority", "created_at"],
    )
    op.execute(
        "ALTER TABLE tbl_whatsapp_keyword_rules ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_keyword_rules
        ON tbl_whatsapp_keyword_rules
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )

    # ----- tbl_whatsapp_keyword_actions ----------------------------
    op.create_table(
        "tbl_whatsapp_keyword_actions",
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
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_keyword_rules.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            postgresql.ENUM(
                "reply_text",
                "reply_template",
                "tag_conversation",
                "assign_to_user",
                "escalate_to_ai",
                name=_ACTION_TYPE_ENUM,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "action_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_keyword_actions_rule_position",
        "tbl_whatsapp_keyword_actions",
        ["rule_id", "position"],
    )
    op.execute(
        "ALTER TABLE tbl_whatsapp_keyword_actions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_keyword_actions
        ON tbl_whatsapp_keyword_actions
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_keyword_actions "
        "ON tbl_whatsapp_keyword_actions"
    )
    op.drop_index(
        "ix_keyword_actions_rule_position",
        table_name="tbl_whatsapp_keyword_actions",
    )
    op.drop_table("tbl_whatsapp_keyword_actions")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_keyword_rules "
        "ON tbl_whatsapp_keyword_rules"
    )
    op.drop_index(
        "ix_keyword_rules_org_enabled_priority",
        table_name="tbl_whatsapp_keyword_rules",
    )
    op.drop_table("tbl_whatsapp_keyword_rules")
    op.execute(f"DROP TYPE {_ACTION_TYPE_ENUM}")
    op.execute(f"DROP TYPE {_MATCH_TYPE_ENUM}")
