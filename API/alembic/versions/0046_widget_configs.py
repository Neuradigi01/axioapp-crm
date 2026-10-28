"""widget_configs — per-org config for the embedded widget.

One row per org (UNIQUE constraint on `org_id`) lazily created on
first `GET /embed/config` or `PUT /embed/config`. Stores a single
JSONB `config` document containing field list, branding hints,
submit-button label, and thank-you copy. The widget JS bundle
fetches it once per render via the public `/embed/config/public`
endpoint.

`updated_by` is a plain UUID (no FK) per the post-0037 convention.

Tenant isolation: standard `apply_rls("widget_configs")` policy on
`org_id`. The public endpoint runs with no JWT — its handler
resolves `org_id` from the embed key and queries explicitly by
`org_id` rather than relying on tenant context. (RLS still applies;
the public path opens a session with no context set, which means the
ORM tenant filter is a no-op and the explicit WHERE does the
authorisation.)

Revision ID: 0046_widget_configs
Revises: 0045_lead_attribution
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0046_widget_configs"
down_revision: Union[str, None] = "0045_lead_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "widget_configs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # UNIQUE — one config per org for v1. Multi-widget per org is a
        # future surface (Quote-request vs. Newsletter vs. Contact form).
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("config", JSONB, nullable=False),
        # No FK — post-0037 convention.
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
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
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_widget_configs_org"),
    )

    apply_rls("widget_configs")


def downgrade() -> None:
    drop_rls("widget_configs")
    op.drop_table("widget_configs")
