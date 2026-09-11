"""Extend ``tbl_embed_keys`` for the custom-events public surface
(``tasks/custom-events`` Step 1).

Additive-only: no rename yet. The rename ``tbl_embed_keys`` →
``tbl_api_keys`` happens in Step 2 alongside the code fold to
``core/public_ingest/`` — bundling them here would blow past Rule 8's
step-size limit AND take the production embed/ai_assistant surfaces
down while doing pure-cosmetic work.

Adds nine columns needed for the events surface + extends the
``resource_type`` CHECK constraint to include ``'events'``. Existing
embed / ai_assistant rows are unaffected — new columns get sensible
defaults; the CHECK just adds a third allowed value.

Columns:

  * ``auto_create_contacts`` — D2 default TRUE. Events keys inherit;
    embed/ai_assistant keys don't consult this (only ingest does).
  * ``default_owner_user_id`` — plain UUID (no FK per post-0037
    convention). Owner picks at key creation; auto-created contacts
    inherit ownership from this. NEVER falls back to org Owner —
    Step 7b's contact_resolution validates it's an active in-org user
    and falls back to round-robin.
  * ``hmac_required`` — per-key toggle. Events keys default TRUE at
    create time (service layer, Step 4); the column default here is
    FALSE so existing embed/ai_assistant rows stay unchanged.
  * ``mode`` — ``live`` | ``test``. ``pk_test_*`` prefix routes to
    dry-run engine (Step 7c); ``pk_live_*`` fires real workflows.
  * ``key_lookup_hash`` — Fernet-encrypted HMAC-of-full-key for O(1)
    prefilter (defeat Argon2id DoS, Step 4). NULL for pre-Step-4
    rows; lazy-backfilled on first successful Argon verify.
  * ``old_key_hash`` + ``old_key_expires_at`` — rotate-with-24h-grace
    (Step 4).
  * ``hmac_secret_encrypted`` — Fernet-encrypted HMAC signing secret.
    NEVER re-revealable after issuance. NULL for embed/ai_assistant
    keys.
  * ``rate_limit_per_minute`` — events keys default 100/min. Embed /
    ai_assistant keep their existing ``rate_limit_per_hour`` semantics
    (both columns coexist; consumers pick which unit to enforce).

Reversible.

Revision ID: 0224_api_keys_events_scope
Revises:     0223_catalog_status
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0224_api_keys_events_scope"
down_revision: str | None = "0223_catalog_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Nine new columns ----------------------------------------------------
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "auto_create_contacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "default_owner_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "hmac_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "mode",
            sa.String(4),
            nullable=False,
            server_default=sa.text("'live'"),
        ),
    )
    op.create_check_constraint(
        "ck_embed_keys_mode",
        "tbl_embed_keys",
        "mode IN ('live', 'test')",
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "key_lookup_hash",
            sa.LargeBinary(),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "old_key_hash",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "old_key_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "hmac_secret_encrypted",
            sa.LargeBinary(),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )

    # --- Partial UNIQUE index over `key_lookup_hash` -------------------------
    # Step 4's HMAC prefilter does O(1) lookup on this. Partial because
    # the column stays NULL for embed/ai_assistant rows that haven't
    # been backfilled yet; a full UNIQUE would refuse the migration.
    op.create_index(
        "ix_embed_keys_lookup_hash",
        "tbl_embed_keys",
        ["key_lookup_hash"],
        unique=True,
        postgresql_where=sa.text("key_lookup_hash IS NOT NULL"),
    )

    # --- Extend resource_type CHECK to include 'events' ----------------------
    # Existing CHECK from 0201: resource_type IN ('lead_form', 'ai_assistant').
    # Drop + recreate with 'events' added.
    op.drop_constraint("ck_embed_keys_resource_type", "tbl_embed_keys", type_="check")
    op.create_check_constraint(
        "ck_embed_keys_resource_type",
        "tbl_embed_keys",
        "resource_type IN ('lead_form', 'ai_assistant', 'events')",
    )


def downgrade() -> None:
    # Undo CHECK extension first.
    op.drop_constraint("ck_embed_keys_resource_type", "tbl_embed_keys", type_="check")
    op.create_check_constraint(
        "ck_embed_keys_resource_type",
        "tbl_embed_keys",
        "resource_type IN ('lead_form', 'ai_assistant')",
    )

    op.drop_index("ix_embed_keys_lookup_hash", table_name="tbl_embed_keys")

    op.drop_column("tbl_embed_keys", "rate_limit_per_minute")
    op.drop_column("tbl_embed_keys", "hmac_secret_encrypted")
    op.drop_column("tbl_embed_keys", "old_key_expires_at")
    op.drop_column("tbl_embed_keys", "old_key_hash")
    op.drop_column("tbl_embed_keys", "key_lookup_hash")
    op.drop_constraint("ck_embed_keys_mode", "tbl_embed_keys", type_="check")
    op.drop_column("tbl_embed_keys", "mode")
    op.drop_column("tbl_embed_keys", "hmac_required")
    op.drop_column("tbl_embed_keys", "default_owner_user_id")
    op.drop_column("tbl_embed_keys", "auto_create_contacts")
