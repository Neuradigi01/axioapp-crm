"""WhatsApp Flows tables + lead-source enum value + permission backfill
(whatsapp-platform-upgrade Step 25).

Three things in one chained migration:

  1. New ``tbl_whatsapp_flows`` — the operator-defined Flow library.
     One row per Flow; the Meta-side flow id is captured on publish.
  2. New ``tbl_whatsapp_flow_submissions`` — append-only inbound
     submissions (one row per ``nfm_reply`` event).
  3. Add ``whatsapp_flow`` to the existing ``lead_source`` enum so
     the auto-action for ``lead_capture`` flows can call
     ``leads.ingest`` with the new source.
  4. Backfill ``whatsapp.flows.manage`` on existing Owner / Admin
     (same fanout pattern as Step 17/20/22/23).

Both tables RLS-isolated via the standard ``app.org_id`` policy.

Chains after ``0112_conv_attribution``.

Revision ID: 0113_wa_flows
Revises: 0112_conv_attribution
Create Date: 2026-06-24 06:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0113_wa_flows"
down_revision: Union[str, None] = "0112_conv_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CATEGORY_VALUES = (
    "appointment_booking",
    "lead_capture",
    "feedback",
    "signup",
    "custom",
)
_STATUS_VALUES = ("draft", "published", "archived")


def upgrade() -> None:
    category_enum = postgresql.ENUM(
        *_CATEGORY_VALUES, name="whatsapp_flow_category"
    )
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="whatsapp_flow_status"
    )
    category_enum.create(op.get_bind(), checkfirst=True)
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tbl_whatsapp_flows",
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
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                *_CATEGORY_VALUES,
                name="whatsapp_flow_category",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'custom'"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_STATUS_VALUES,
                name="whatsapp_flow_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "json_definition",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Meta-side flow id captured after the first publish.
        sa.Column("meta_flow_id", sa.String(64), nullable=True),
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
        ),
        sa.UniqueConstraint(
            "org_id", "name", name="uq_wa_flows_org_name"
        ),
    )
    op.create_index(
        "ix_wa_flows_org_category",
        "tbl_whatsapp_flows",
        ["org_id", "category"],
    )

    op.create_table(
        "tbl_whatsapp_flow_submissions",
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
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_whatsapp_flows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Meta's `name` token from the nfm_reply envelope — useful
        # when the local flow row was deleted but the submission
        # still arrived.
        sa.Column("flow_token", sa.String(128), nullable=True),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "response_data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Capture the downstream auto-action result so the operator
        # can drill from a submission → the lead / appointment /
        # review it produced.
        sa.Column(
            "action_taken", sa.String(64), nullable=True
        ),
        sa.Column(
            "action_entity_id",
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
        "ix_wa_flow_submissions_flow_created",
        "tbl_whatsapp_flow_submissions",
        ["flow_id", "created_at"],
    )
    op.create_index(
        "ix_wa_flow_submissions_org_contact",
        "tbl_whatsapp_flow_submissions",
        ["org_id", "contact_id"],
    )

    # RLS
    for table in ("tbl_whatsapp_flows", "tbl_whatsapp_flow_submissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table.replace('tbl_', '')}
                ON {table}
                USING (org_id = current_setting('app.org_id', true)::uuid)
                WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
            """
        )

    # Add `whatsapp_flow` to the existing lead_source enum so the
    # auto-action can call `ingest()` with the new source.
    op.execute(
        "ALTER TYPE lead_source ADD VALUE IF NOT EXISTS 'whatsapp_flow'"
    )

    # Backfill the new permission on existing Owner + Admin rows.
    op.execute(
        """
        INSERT INTO tbl_permissions (key, description, module)
        VALUES ('whatsapp.flows.manage',
                'Manage WhatsApp Flows (create / publish / test-send)',
                'whatsapp')
        ON CONFLICT (key) DO NOTHING
        """
    )
    for role_name in ("Owner", "Admin"):
        op.execute(
            f"""
            INSERT INTO tbl_role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM tbl_roles r
            CROSS JOIN tbl_permissions p
            WHERE r.name = '{role_name}'
              AND p.key = 'whatsapp.flows.manage'
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    for role_name in ("Owner", "Admin"):
        op.execute(
            f"""
            DELETE FROM tbl_role_permissions
            WHERE role_id IN (
                SELECT id FROM tbl_roles WHERE name = '{role_name}'
            )
            AND permission_id IN (
                SELECT id FROM tbl_permissions WHERE key = 'whatsapp.flows.manage'
            )
            """
        )
    # The lead_source enum can't easily DROP VALUE in Postgres;
    # leave the value in place. Subsequent re-upgrade is a no-op.
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_whatsapp_flow_submissions ON tbl_whatsapp_flow_submissions"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_whatsapp_flows ON tbl_whatsapp_flows"
    )
    op.drop_index(
        "ix_wa_flow_submissions_org_contact",
        table_name="tbl_whatsapp_flow_submissions",
    )
    op.drop_index(
        "ix_wa_flow_submissions_flow_created",
        table_name="tbl_whatsapp_flow_submissions",
    )
    op.drop_table("tbl_whatsapp_flow_submissions")
    op.drop_index(
        "ix_wa_flows_org_category", table_name="tbl_whatsapp_flows"
    )
    op.drop_table("tbl_whatsapp_flows")
    sa.Enum(name="whatsapp_flow_status").drop(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(name="whatsapp_flow_category").drop(
        op.get_bind(), checkfirst=True
    )
