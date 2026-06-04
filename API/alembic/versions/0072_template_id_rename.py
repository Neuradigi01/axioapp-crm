"""Rename organizations.pack_id and pack_version to template_id and
template_version.

Frees the name `pack_id` for a future subscription-tier column without
disturbing the rest of the data model. Pure column rename — every
existing row's value carries over (e.g. `'furniture'`, `'base'`,
`'pending'`). No data migration, no constraint change, no RLS policy
change (org-scoped policies key off `org_id`, not these columns).

The `organizations.template_id` server default flips from the legacy
`'furniture'` to `'pending'`, matching the new self-signup contract
introduced in onboarding-setup Step 2. Existing rows are unaffected
(server_default applies only on INSERT-without-value).

Revision ID: 0072_template_id_rename
Revises:    0071_saved_views
Create Date: 2026-06-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0072_template_id_rename"
down_revision: Union[str, None] = "0071_saved_views"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "pack_id",
        new_column_name="template_id",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        existing_server_default=sa.text("'furniture'"),
        server_default=sa.text("'pending'"),
    )
    op.alter_column(
        "organizations",
        "pack_version",
        new_column_name="template_version",
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "organizations",
        "template_version",
        new_column_name="pack_version",
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )
    op.alter_column(
        "organizations",
        "template_id",
        new_column_name="pack_id",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        existing_server_default=sa.text("'pending'"),
        server_default=sa.text("'furniture'"),
    )
