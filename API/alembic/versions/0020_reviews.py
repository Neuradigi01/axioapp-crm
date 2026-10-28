"""reviews

One tenant-scoped, RLS-on table + `review_status` ENUM. Indexes:
  - reviews(org_id, rating)      for distribution group-bys
  - reviews(org_id, source)      for per-source filtering
  - reviews(org_id, created_at)  for the "last 7 days" alert query

Revision ID: 0020_reviews
Revises: 0019_calls
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0020_reviews"
down_revision: Union[str, None] = "0019_calls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("pending_reply", "replied", "escalated")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="review_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reviews",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'pending_reply'"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("ARRAY[]::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_1_5"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["replied_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_org_rating", "reviews", ["org_id", "rating"])
    op.create_index("ix_reviews_org_source", "reviews", ["org_id", "source"])
    op.create_index(
        "ix_reviews_org_created_at", "reviews", ["org_id", "created_at"]
    )

    apply_rls("reviews")


def downgrade() -> None:
    drop_rls("reviews")
    op.drop_index("ix_reviews_org_created_at", table_name="reviews")
    op.drop_index("ix_reviews_org_source", table_name="reviews")
    op.drop_index("ix_reviews_org_rating", table_name="reviews")
    op.drop_table("reviews")
    postgresql.ENUM(name="review_status").drop(
        op.get_bind(), checkfirst=True
    )
