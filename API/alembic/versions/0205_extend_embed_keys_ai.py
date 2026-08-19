"""Extend ``tbl_embed_keys`` for the AI-assistants public surface
(``tasks/ai-assistants`` Step 14).

Adds three columns needed by the public embed router:

  * ``allowed_origins`` — array of allowed ``Origin`` headers. Empty
    array = no origin check (advisory; real defence is rate-limit +
    budget cap + Turnstile). Bounded to the same 253-char / 32-item
    caps the assistants ``allowed_domains`` field enforces.
  * ``rate_limit_per_hour`` — per-key hourly cap for the sliding-
    window Redis limiter. 300 default matches the plan doc.
  * ``grace_expires_at`` — set on rotate-with-grace so the old key
    keeps working for a bounded window while the operator swaps the
    new key into their site. Sweeper in Step 17 finalises the
    revoke; ``expire_grace(now)`` DAL helper reads it.

Step 5's migration (``0201_ai_assistants_schema``) already added the
``resource_type`` / ``resource_id`` columns and the composite
``ix_embed_keys_resource`` index — we don't touch those here.

Revision ID: 0205_extend_embed_keys_ai
Revises:     0204_bf_ai_prompt_templates
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0205_extend_embed_keys_ai"
down_revision: str | None = "0204_bf_ai_prompt_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "allowed_origins",
            sa.dialects.postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "rate_limit_per_hour",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("300"),
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "grace_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial index over rows whose grace window is set — the Step 17
    # sweeper scans this range every 5 minutes; a full-table scan
    # would be wasteful once orgs accumulate keys.
    op.create_index(
        "ix_embed_keys_grace_expires_at",
        "tbl_embed_keys",
        ["grace_expires_at"],
        postgresql_where=sa.text("grace_expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_embed_keys_grace_expires_at", table_name="tbl_embed_keys")
    op.drop_column("tbl_embed_keys", "grace_expires_at")
    op.drop_column("tbl_embed_keys", "rate_limit_per_hour")
    op.drop_column("tbl_embed_keys", "allowed_origins")
