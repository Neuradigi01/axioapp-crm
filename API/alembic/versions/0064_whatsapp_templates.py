"""whatsapp_templates — per-(org, integration) cache of Meta-approved
WhatsApp message templates.

Populated by the Step-3.5.4 sync job
(`integrations.whatsapp.templates.sync_templates`) which pulls Meta's
`/{waba_id}/message_templates` endpoint and upserts. Read by the
Step-3.5.5 campaign template picker.

Body / header / footer / variable_count are precomputed from Meta's
`components[]` array so the picker doesn't re-parse the JSON on every
render. `meta_template_id` is kept for traceability and idempotent
upsert (we key on `(integration_id, name, language)` rather than on
the Meta id because Meta's id can change when a template is edited).

Hard-delete behavior: when a template disappears from Meta's response,
the sync job drops the local row. Meta is the source of truth. The
`campaigns.template` column stores the name as text, so campaign
history survives template deletion (the campaign just can't dispatch
to that template name anymore).

Tenant-scoped + RLS via `apply_rls("whatsapp_templates")`.

Revision ID: 0064_whatsapp_templates
Revises: 0063_drop_pack_users_id_fks
Create Date: 2026-05-28 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0064_whatsapp_templates"
down_revision: Union[str, None] = "0063_drop_pack_users_id_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("header_type", sa.Text(), nullable=True),
        sa.Column("header_text", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column(
            "variable_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("meta_template_id", sa.Text(), nullable=True),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_whatsapp_templates_integration_name_lang",
        "whatsapp_templates",
        ["integration_id", "name", "language"],
        unique=True,
    )
    op.create_index(
        "ix_whatsapp_templates_org_status",
        "whatsapp_templates",
        ["org_id", "status"],
    )

    apply_rls("whatsapp_templates")


def downgrade() -> None:
    drop_rls("whatsapp_templates")
    op.drop_index(
        "ix_whatsapp_templates_org_status",
        table_name="whatsapp_templates",
    )
    op.drop_index(
        "uq_whatsapp_templates_integration_name_lang",
        table_name="whatsapp_templates",
    )
    op.drop_table("whatsapp_templates")
