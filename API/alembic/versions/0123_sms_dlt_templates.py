"""SMS-DLT extension table for the central template library
(``tasks/template-library`` Step 12).

India's TRAI mandate (Telecom Regulatory Authority) requires every
SMS template to be registered with a DLT (Distributed Ledger
Technology) portal — Jio's, Airtel's, or VI's. Once registered the
operator gets back a DLT template id + a registered sender header
(6-char alphanumeric). All future SMS sends to Indian numbers must
reference these ids; non-compliant sends are blocked at the operator
gateway.

We DON'T submit to DLT from the CRM (the portals are TRAI-mandated
external; standard CRM pattern is manual ID capture). Instead this
table stores the operator-supplied ids alongside the central
``tbl_message_templates`` row. The future SMS-provider adapter
reads these at send time.

Schema:

  ``tbl_sms_dlt_templates``
    id                       UUID PK
    org_id                   FK → tbl_organizations
    message_template_id      FK → tbl_message_templates  (ON DELETE CASCADE)
    dlt_entity_id            text — operator's PE id (Principal Entity)
    dlt_template_id          text — TRAI-issued template id
    dlt_content_category     enum (transactional | promotional |
                                   service_explicit | service_implicit)
    dlt_header               text — sender id (6-char alphanumeric)
    dlt_principal_entity_id  text — sometimes distinct from entity_id
                                    (telco-specific quirk)
    dlt_template_status      enum (registered | pending | rejected)
    dlt_registered_at        timestamptz nullable
    dlt_rejection_reason     text nullable
    created_at, updated_at   timestamptz

Constraints:
  * Unique (message_template_id) — one DLT extension per central row.
  * Unique (org_id, dlt_template_id) WHERE dlt_template_id IS NOT NULL
    — TRAI assigns unique ids per registered entity, but we can't
    enforce that across orgs.
  * RLS via org_id.

Chains after ``0122_campaigns_template_fk``.

Revision ID: 0123_sms_dlt_templates
Revises: 0122_campaigns_template_fk
Create Date: 2026-06-25 19:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0123_sms_dlt_templates"
down_revision: Union[str, None] = "0122_campaigns_template_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DLT_CATEGORY_VALUES = (
    "transactional",
    "promotional",
    "service_explicit",
    "service_implicit",
)
_DLT_STATUS_VALUES = ("registered", "pending", "rejected")


def upgrade() -> None:
    category_enum = postgresql.ENUM(
        *_DLT_CATEGORY_VALUES, name="sms_dlt_content_category"
    )
    category_enum.create(op.get_bind(), checkfirst=True)
    status_enum = postgresql.ENUM(
        *_DLT_STATUS_VALUES, name="sms_dlt_template_status"
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tbl_sms_dlt_templates",
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
            "message_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dlt_entity_id", sa.Text(), nullable=True),
        sa.Column("dlt_template_id", sa.Text(), nullable=True),
        sa.Column(
            "dlt_content_category",
            postgresql.ENUM(
                *_DLT_CATEGORY_VALUES,
                name="sms_dlt_content_category",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'transactional'"),
        ),
        sa.Column("dlt_header", sa.String(6), nullable=True),
        sa.Column("dlt_principal_entity_id", sa.Text(), nullable=True),
        sa.Column(
            "dlt_template_status",
            postgresql.ENUM(
                *_DLT_STATUS_VALUES,
                name="sms_dlt_template_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "dlt_registered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("dlt_rejection_reason", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "message_template_id",
            name="uq_sms_dlt_message_template_id",
        ),
    )
    op.create_index(
        "ix_sms_dlt_templates_message_template_id",
        "tbl_sms_dlt_templates",
        ["message_template_id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sms_dlt_templates_org_dlt_id "
        "ON tbl_sms_dlt_templates (org_id, dlt_template_id) "
        "WHERE dlt_template_id IS NOT NULL"
    )

    # RLS — standard tenant-isolation policy.
    op.execute("ALTER TABLE tbl_sms_dlt_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tbl_sms_dlt_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_sms_dlt_templates
            ON tbl_sms_dlt_templates
            USING (org_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_sms_dlt_templates "
        "ON tbl_sms_dlt_templates"
    )
    op.execute("DROP INDEX IF EXISTS uq_sms_dlt_templates_org_dlt_id")
    op.drop_index(
        "ix_sms_dlt_templates_message_template_id",
        table_name="tbl_sms_dlt_templates",
    )
    op.drop_table("tbl_sms_dlt_templates")
    sa.Enum(name="sms_dlt_template_status").drop(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(name="sms_dlt_content_category").drop(
        op.get_bind(), checkfirst=True
    )
