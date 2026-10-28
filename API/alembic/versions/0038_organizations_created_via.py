"""Add organizations.created_via — provenance for self-signup orgs.

Distinguishes self-signup orgs (`'normal_signup'`) from seeded demo
orgs (`'seed'`) and admin-provisioned orgs (`'admin'`). Used by
RBAC-track Step 1 (signup creates org + Owner).

Existing rows are backfilled to `'seed'` since they all come from the
seed scripts. The column carries a server default so future inserts
that omit it default to `'normal_signup'`.

Revision ID: 0038_organizations_created_via
Revises: 0037_drop_users_id_fks
Create Date: 2026-05-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0038_organizations_created_via"
down_revision: Union[str, None] = "0037_drop_users_id_fks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "created_via",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE organizations SET created_via = 'seed' WHERE created_via IS NULL"
    )
    op.alter_column(
        "organizations",
        "created_via",
        nullable=False,
        server_default=sa.text("'normal_signup'"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "created_via")
