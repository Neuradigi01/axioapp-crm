"""Add image_url column to catalog_items.

Stores the public URL of an uploaded cover image, served via the
`/files/...` static mount. Nullable — existing rows keep the emoji
placeholder on the card grid until an image is uploaded. Pure
ALTER TABLE, no data migration, no RLS change (the table already
has RLS from `0015_catalog_items`).

Revision ID: 0073_catalog_image_url
Revises:    0072_template_id_rename
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0073_catalog_image_url"
down_revision: Union[str, None] = "0072_template_id_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("image_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalog_items", "image_url")
