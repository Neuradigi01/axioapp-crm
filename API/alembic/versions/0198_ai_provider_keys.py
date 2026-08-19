"""BYOK provider-key store — ``core/integrations/ai/``
(``tasks/ai-assistants`` Step 1).

Two tenant-scoped tables back the org-scoped OpenAI (v1: OpenAI only)
API-key store + the daily/monthly USD budget ledger the chat runtime
(Step 9) will consult before every LLM call.

  * ``tbl_ai_provider_keys`` — one row per stored API key. Ciphertext
    is AES-GCM output; nonce lives alongside; AAD binds the ciphertext
    to ``(org_id, key_id, key_version)`` so an insider with SQL write
    cannot copy row A's ciphertext into row B and cause org B's
    traffic to be billed against org A's OpenAI account.
    Unique ``(org_id, provider, fingerprint_sha256)`` gives us the
    "this key is already stored" dedup + the cross-org copy detection.
  * ``tbl_org_ai_cost_budget`` — one row per org (UNIQUE), tracks
    day/month buckets + spent counters + configurable daily/monthly
    USD caps. Advisory helper ``charge_budget(dry_run)`` (in the
    service) reads/mutates this row from the runtime and refuses the
    call when a cap would be exceeded.

Two ENUMs:

  * ``ai_provider`` — ``openai`` only in v1; ``anthropic`` / ``google``
    / ``openrouter`` reserved so future adapters land without a
    schema change.
  * ``ai_provider_test_status`` — ``untested`` / ``success`` /
    ``failed`` for the operator-visible "does this key work?" pill.

RLS policies use the standard ``org_id = current_setting('app.current_org_id')``
gate identical to every other tenant-scoped table.

Chains after ``0197_fix_activity_entity_type``. Reversible.

Revision ID: 0198_ai_provider_keys
Revises:     0197_fix_activity_entity_type
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0198_ai_provider_keys"
down_revision: str | None = "0197_fix_activity_entity_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- ENUMs ----------------------------------------------------------------
    ai_provider = postgresql.ENUM(
        "openai",
        "anthropic",
        "google",
        "openrouter",
        name="ai_provider",
        create_type=True,
    )
    ai_provider.create(bind, checkfirst=True)

    ai_provider_test_status = postgresql.ENUM(
        "untested",
        "success",
        "failed",
        name="ai_provider_test_status",
        create_type=True,
    )
    ai_provider_test_status.create(bind, checkfirst=True)

    # --- tbl_ai_provider_keys -------------------------------------------------
    op.create_table(
        "tbl_ai_provider_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(name="ai_provider", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "label",
            sa.String(120),
            nullable=False,
            server_default=sa.text("'Default'"),
        ),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column(
            "key_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # SHA-256 hash of the plaintext API key. 32 bytes. Enables
        # ("this key is already stored") dedup within an org and gives
        # security teams a cross-org "same key material" detection signal.
        sa.Column("fingerprint_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column(
            "test_status",
            postgresql.ENUM(name="ai_provider_test_status", create_type=False),
            nullable=False,
            server_default=sa.text("'untested'"),
        ),
        sa.Column("test_last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_last_error", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Dedup within an org + cross-org copy detection JOIN target.
    op.create_unique_constraint(
        "uq_ai_provider_keys_org_provider_fp",
        "tbl_ai_provider_keys",
        ["org_id", "provider", "fingerprint_sha256"],
    )
    op.create_index(
        "ix_ai_provider_keys_org_provider_revoked",
        "tbl_ai_provider_keys",
        ["org_id", "provider", "revoked_at"],
    )

    # --- tbl_org_ai_cost_budget ----------------------------------------------
    op.create_table(
        "tbl_org_ai_cost_budget",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "daily_cap_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("10.00"),
        ),
        sa.Column(
            "monthly_cap_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("200.00"),
        ),
        sa.Column(
            "spent_today_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "spent_month_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # day_bucket is a DATE — rolls over at UTC midnight; the service
        # helper detects a change and resets ``spent_today_usd``.
        sa.Column("day_bucket", sa.Date(), nullable=True),
        # month_bucket is text YYYY-MM (matches ``date_trunc('month')::text``
        # output but stored explicitly so cross-timezone rollover semantics
        # are chosen in application code, not the DB).
        sa.Column("month_bucket", sa.String(7), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- RLS policies ---------------------------------------------------------
    for table in ("tbl_ai_provider_keys", "tbl_org_ai_cost_budget"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )


def downgrade() -> None:
    # Drop policies + tables in FK-safe order (both are org-owned; no
    # inter-table FKs between them).
    for table in ("tbl_org_ai_cost_budget", "tbl_ai_provider_keys"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table("tbl_org_ai_cost_budget")

    op.execute("DROP INDEX IF EXISTS ix_ai_provider_keys_org_provider_revoked")
    op.execute("DROP CONSTRAINT IF EXISTS uq_ai_provider_keys_org_provider_fp")
    op.drop_table("tbl_ai_provider_keys")

    for enum_name in ("ai_provider_test_status", "ai_provider"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
