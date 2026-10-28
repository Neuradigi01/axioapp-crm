"""campaigns: template_id + template_variables — WhatsApp template campaigns

Step 3.5.5 adds two columns to `campaigns` so a campaign author can target
an approved Meta template instead of a free-text body:

  - `template_id`        FK → whatsapp_templates(id), ON DELETE SET NULL.
                         Nullable for non-WA channels and for legacy
                         free-text campaigns.
  - `template_variables` JSONB — operator's variable bindings. Shape:
                         {"1": {"kind":"static","value":"30%"},
                          "2": {"kind":"field","value":"full_name"}}
                         resolved per-contact in Step 3.5.6 dispatch.

`template` (the free-text body) is altered to nullable — a WA template
campaign has `template_id` set instead. Schema validation (Step 3.5.5)
enforces "exactly one of template or template_id".

ON DELETE SET NULL on the FK preserves campaign history if Meta deletes
the template (Step 3.5.4 hard-delete behavior on sync). The campaign's
audit trail is intact; only the dispatch path will fail with a clear
"template no longer exists" error.

Revision ID: 0065_campaigns_template_id
Revises: 0064_whatsapp_templates
Create Date: 2026-05-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0065_campaigns_template_id"
down_revision: Union[str, None] = "0064_whatsapp_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "template_variables",
            JSONB(),
            nullable=True,
        ),
    )
    op.alter_column(
        "campaigns",
        "template",
        existing_type=sa.String(length=4096),
        nullable=True,
    )
    op.create_index(
        "ix_campaigns_template_id",
        "campaigns",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_template_id", table_name="campaigns")
    # Re-tighten the template NOT NULL. Existing rows with a NULL
    # template (WA template campaigns) would block this — operator
    # would have to backfill or drop those rows first. The downgrade
    # is best-effort and assumes a clean rollback window.
    op.alter_column(
        "campaigns",
        "template",
        existing_type=sa.String(length=4096),
        nullable=False,
    )
    op.drop_column("campaigns", "template_variables")
    op.drop_column("campaigns", "template_id")
