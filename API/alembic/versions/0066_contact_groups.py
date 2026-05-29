"""contact_groups + contact_group_members — saved audiences for
campaigns (Step 3.5.7).

Two tables backing the "Contact group" entity:

  - `contact_groups`: one row per saved audience. `is_dynamic=true`
    stores a `filter_json` ({q, source, tag, ...}) that's re-evaluated
    every time the group's contacts are resolved. `is_dynamic=false`
    is a snapshot — the explicit member list lives in the bridge
    table below and never auto-includes new matching contacts.

  - `contact_group_members`: bridge `(group_id × contact_id)` populated
    ONLY for static groups. Dynamic groups leave it empty and resolve
    on demand via the contacts query builder.

Why both modes:
  - Dynamic covers ongoing segments ("VIP Customers", "Bangalore branch").
  - Static covers one-off blasts ("XLSX upload from sales_leads_q3",
    "Saturday event attendees") where the operator wants exactly
    these N contacts and no auto-inclusion later.

The Step 3.5.9 audience builder reads both, and Step 3.5.10's XLSX
import optionally creates a static group from the upload.

Tenant-scoped + RLS on both tables. UNIQUE(`org_id`, `name`) prevents
duplicate group names per org. UNIQUE(`group_id`, `contact_id`)
prevents the same contact being added twice to a static group.

Revision ID: 0066_contact_groups
Revises: 0065_campaigns_template_id
Create Date: 2026-05-28 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0066_contact_groups"
down_revision: Union[str, None] = "0065_campaigns_template_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_groups",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_dynamic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("filter_json", JSONB(), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_contact_groups_org_name",
        "contact_groups",
        ["org_id", "name"],
        unique=True,
    )
    op.create_index(
        "ix_contact_groups_org_dynamic",
        "contact_groups",
        ["org_id", "is_dynamic"],
    )

    op.create_table(
        "contact_group_members",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["contact_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_contact_group_members_group_contact",
        "contact_group_members",
        ["group_id", "contact_id"],
        unique=True,
    )
    op.create_index(
        "ix_contact_group_members_org_group",
        "contact_group_members",
        ["org_id", "group_id"],
    )

    apply_rls("contact_groups")
    apply_rls("contact_group_members")


def downgrade() -> None:
    drop_rls("contact_group_members")
    drop_rls("contact_groups")
    op.drop_index(
        "ix_contact_group_members_org_group",
        table_name="contact_group_members",
    )
    op.drop_index(
        "uq_contact_group_members_group_contact",
        table_name="contact_group_members",
    )
    op.drop_table("contact_group_members")
    op.drop_index(
        "ix_contact_groups_org_dynamic", table_name="contact_groups"
    )
    op.drop_index("uq_contact_groups_org_name", table_name="contact_groups")
    op.drop_table("contact_groups")
