"""embed_keys — per-org public API keys for the embeddable widget.

One row per issued key. The plaintext `pk_live_<32-base62-chars>` is
returned to the Owner exactly once (in the issue endpoint's response)
and never persisted — only a bcrypt hash + a 11-char display prefix
are stored. Lookup at submission time scans by prefix (partial index
over non-revoked rows) then bcrypt-verifies the candidate(s).

`created_by` / `revoked_by` are plain UUIDs with no FK to `users(id)`
per the post-0037 convention documented in `0039_standard_field_overrides`
(legacy `users` table on soak).

`last_used_ip` stores a 16-char SHA-256 hex prefix of the caller IP,
not the IP itself — keeps the abuse-investigation surface in Step 9
useful for grouping without storing PII.

Revision ID: 0044_embed_keys
Revises: 0043_seed_system_import_presets
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0044_embed_keys"
down_revision: Union[str, None] = "0043_seed_system_import_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embed_keys",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        # 11-char display prefix: "pk_live_AbC". CHAR(11) keeps the
        # partial index narrow and lookups deterministic in length.
        sa.Column("prefix", sa.CHAR(length=11), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        # No FK — post-0037 convention.
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # SHA-256 hex prefix of the IP, not the IP itself. Sized for the
        # 16-char projection produced by `hashlib.sha256(ip).hexdigest()[:16]`.
        sa.Column("last_used_ip", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial index — only non-revoked rows participate, so the lookup
    # hot path is a tight scan over live keys. The widget submission
    # endpoint (Step 2) queries `WHERE prefix = :p AND revoked_at IS NULL`.
    op.execute(
        "CREATE INDEX ix_embed_keys_prefix_live ON embed_keys (prefix) "
        "WHERE revoked_at IS NULL"
    )
    op.create_index(
        "ix_embed_keys_org_created",
        "embed_keys",
        ["org_id", sa.text("created_at DESC")],
    )

    apply_rls("embed_keys")


def downgrade() -> None:
    drop_rls("embed_keys")
    op.drop_index("ix_embed_keys_org_created", table_name="embed_keys")
    op.execute("DROP INDEX IF EXISTS ix_embed_keys_prefix_live")
    op.drop_table("embed_keys")
