"""saved_views table (Step 7).

Stores per-user named "views" — bundles of filter + sort + columns +
scope + view-mode (list/pipeline) — that the user can re-apply with one
click on `/user/leads`. Same shape is reusable for contacts, walk-ins,
tasks; the `entity` column gates which list the view belongs to.

Visibility:
  - RLS enforces standard `org_id = current_org` tenant isolation.
  - Owner/shared visibility (i.e. "shared views are visible to the
    whole org, owned views are visible only to the owner") is enforced
    in the service-layer WHERE clause — the codebase doesn't push
    `current_user_id` into a PG session var, so a custom RLS policy
    would have nothing to read.

Owner pointer:
  - `owner_user_id UUID` matches `User.legacy_uuid` (the UUID the rest
    of the codebase uses for cross-table user references).
  - **No FK constraint** — per migration 0062 the codebase dropped all
    FKs targeting the user tables. The service layer validates the
    UUID resolves to a current-org member when needed.

Revision ID: 0071_saved_views
Revises: 0070_leads_scoring
Create Date: 2026-06-01 12:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0071_saved_views"
down_revision: Union[str, None] = "0070_leads_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        # No FK — see module note. Validated app-side.
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column(
            "shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # One name per owner-per-entity. Rename across owners is fine; the
    # team-shared list disambiguates by owner separately.
    op.create_index(
        "uq_saved_views_owner_entity_name",
        "saved_views",
        ["owner_user_id", "entity", "name"],
        unique=True,
    )
    # Hot path: list for the current org + entity.
    op.create_index(
        "ix_saved_views_org_entity",
        "saved_views",
        ["org_id", "entity"],
    )

    apply_rls("saved_views")


def downgrade() -> None:
    drop_rls("saved_views")
    op.drop_index("ix_saved_views_org_entity", table_name="saved_views")
    op.drop_index("uq_saved_views_owner_entity_name", table_name="saved_views")
    op.drop_table("saved_views")
