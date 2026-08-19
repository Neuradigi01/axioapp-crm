"""AI Assistants foundation — 5 tables + 5 enums + RLS + 2 ALTERs
(``tasks/ai-assistants`` Step 5).

Ships the schema Step 6 (assistant CRUD), Step 9 (chat runtime),
Step 10 (knowledge ingest), Step 14 (embed keys), Step 16
(conversation history + analytics) will fill in.

Five tables land here (all tenant-scoped, all RLS-on):

  * ``tbl_ai_assistants`` — one row per assistant.
  * ``tbl_ai_assistant_knowledge`` — one row per uploaded / typed /
    URL knowledge source. Content-hash unique per assistant.
  * ``tbl_ai_assistant_chunks`` — one row per embedded chunk
    (``embedding VECTOR(1536)``); HNSW index on the embedding
    column + composite b-tree on ``(org_id, status)``.
  * ``tbl_ai_assistant_message_meta`` — AI-specific side-table on
    ``tbl_messages`` (PK = ``message_id``). ``assistant_id`` is
    SET NULL on assistant delete so history survives.
  * ``tbl_ai_assistant_instruction_audit`` — append-only diff log
    for high-signal field changes.

Five new ENUMs: ``ai_assistant_status``, ``knowledge_source_type``,
``knowledge_status``, ``chunk_status``, ``cost_status``.

Two ALTERs on existing tables:

  * ``tbl_embed_keys`` gets ``resource_type`` (CHECK-constrained
    text; default ``'lead_form'`` so existing rows backfill
    automatically) + ``resource_id`` (nullable UUID; enforced NOT
    NULL for ``ai_assistant`` rows in Step 14's service).
  * ``conversation_channel`` ENUM gets a new value ``'ai_widget'``
    — AI-widget conversations reuse ``tbl_conversations``
    (Architect review S1: kill the parallel conversation tables
    so inbox + human-handoff work for free).

Chains after ``0200_install_pgvector``. Reversible.

Revision ID: 0201_ai_assistants_schema
Revises:     0200_install_pgvector
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0201_ai_assistants_schema"
down_revision: str | None = "0200_install_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- ENUMs ----------------------------------------------------------------
    ai_assistant_status = postgresql.ENUM(
        "draft",
        "active",
        "archived",
        name="ai_assistant_status",
        create_type=True,
    )
    ai_assistant_status.create(bind, checkfirst=True)

    knowledge_source_type = postgresql.ENUM(
        "file",
        "text",
        "url",
        name="knowledge_source_type",
        create_type=True,
    )
    knowledge_source_type.create(bind, checkfirst=True)

    knowledge_status = postgresql.ENUM(
        "pending",
        "processing",
        "ready",
        "failed_no_text",
        "failed_stuck",
        "failed_ingest",
        "pending_delete",
        "pending_cancel",
        name="knowledge_status",
        create_type=True,
    )
    knowledge_status.create(bind, checkfirst=True)

    chunk_status = postgresql.ENUM(
        "ready",
        "pending_delete",
        name="chunk_status",
        create_type=True,
    )
    chunk_status.create(bind, checkfirst=True)

    cost_status = postgresql.ENUM(
        "pending_llm_confirm",
        "confirmed",
        "reconciled",
        "failed",
        name="cost_status",
        create_type=True,
    )
    cost_status.create(bind, checkfirst=True)

    # Extend the existing conversation_channel enum with 'ai_widget'.
    # PG 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as
    # long as the new value isn't referenced in the same tx.
    op.execute(
        "ALTER TYPE conversation_channel ADD VALUE IF NOT EXISTS 'ai_widget'"
    )

    # --- tbl_ai_assistants ----------------------------------------------------
    op.create_table(
        "tbl_ai_assistants",
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="ai_assistant_status", create_type=False),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_ai_provider_keys.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column(
            "temperature",
            sa.Numeric(3, 2),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column(
            "stop_keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "retry_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fallback_message",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'I''m sorry, I can''t help with that right now.'"),
        ),
        sa.Column(
            "allowed_domains",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "output_sanitizer_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("budget_cap_override_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # Plain UUID (no FK) — matches the workflows/chatbots
        # convention. The users table is `users` (legacy, pre-rename)
        # and hard-linking would couple this migration to the rename
        # timeline. Application layer looks up the user by id.
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "interface_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "styling_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
    # Case-insensitive uniqueness on name per org.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_ai_assistants_org_lower_name
            ON tbl_ai_assistants (org_id, lower(name))
        """
    )
    op.create_index(
        "ix_ai_assistants_org_status",
        "tbl_ai_assistants",
        ["org_id", "status"],
    )

    # --- tbl_ai_assistant_knowledge ------------------------------------------
    op.create_table(
        "tbl_ai_assistant_knowledge",
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
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_ai_assistants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            postgresql.ENUM(name="knowledge_source_type", create_type=False),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="knowledge_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column(
            "progress_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
    op.create_unique_constraint(
        "uq_ai_assistant_knowledge_assistant_hash",
        "tbl_ai_assistant_knowledge",
        ["assistant_id", "content_hash"],
    )
    op.create_index(
        "ix_ai_assistant_knowledge_assistant_status",
        "tbl_ai_assistant_knowledge",
        ["assistant_id", "status"],
    )

    # --- tbl_ai_assistant_chunks ---------------------------------------------
    op.create_table(
        "tbl_ai_assistant_chunks",
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
            "knowledge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_ai_assistant_knowledge.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # VECTOR(1536) — sized for OpenAI text-embedding-3-small.
        sa.Column("embedding", sa.dialects.postgresql.JSONB, nullable=False),  # placeholder, replaced below
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="chunk_status", create_type=False),
            nullable=False,
            server_default=sa.text("'ready'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # SQLAlchemy doesn't ship a native ``VECTOR`` DDL renderer at
    # the ``sa.Column`` level; the ``pgvector.sqlalchemy.Vector``
    # type works fine in ORM code but requires the extension's
    # own import path for DDL. Simpler + adapter-agnostic: swap
    # the placeholder column type to the real vector type via
    # raw DDL. Cost: one extra migration statement; benefit: this
    # migration doesn't need to import the pgvector Python package
    # (keeps migrations importable on a bare Python).
    op.execute("ALTER TABLE tbl_ai_assistant_chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE tbl_ai_assistant_chunks ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_index(
        "ix_ai_assistant_chunks_org_status",
        "tbl_ai_assistant_chunks",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_ai_assistant_chunks_knowledge",
        "tbl_ai_assistant_chunks",
        ["knowledge_id"],
    )
    op.create_unique_constraint(
        "uq_ai_assistant_chunks_knowledge_index",
        "tbl_ai_assistant_chunks",
        ["knowledge_id", "chunk_index"],
    )
    # HNSW index for cosine similarity. NOT a partial index — partial
    # HNSW requires pgvector 0.7+ and adds no value in v1 because the
    # ``WHERE status = 'ready'`` predicate in the query is already
    # index-supported by the composite ``(org_id, status)`` b-tree
    # above. The planner combines the two indexes via bitmap AND.
    op.execute(
        """
        CREATE INDEX ix_ai_assistant_chunks_embedding_hnsw
            ON tbl_ai_assistant_chunks
            USING hnsw (embedding vector_cosine_ops)
        """
    )

    # --- tbl_ai_assistant_message_meta ---------------------------------------
    op.create_table(
        "tbl_ai_assistant_message_meta",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_ai_assistants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column(
            "prompt_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "completion_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_status",
            postgresql.ENUM(name="cost_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending_llm_confirm'"),
        ),
        sa.Column("provider_error", sa.Text(), nullable=True),
        sa.Column(
            "retrieved_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
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
    op.create_index(
        "ix_ai_assistant_message_meta_org_assistant_created",
        "tbl_ai_assistant_message_meta",
        ["org_id", "assistant_id", "created_at"],
    )

    # --- tbl_ai_assistant_instruction_audit ----------------------------------
    op.create_table(
        "tbl_ai_assistant_instruction_audit",
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
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_ai_assistants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Plain UUID (no FK) — matches the workflows/chatbots
        # convention (see created_by_user_id above).
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_ai_assistant_instruction_audit_assistant_changed",
        "tbl_ai_assistant_instruction_audit",
        ["assistant_id", "changed_at"],
    )

    # --- RLS policies ---------------------------------------------------------
    for table in (
        "tbl_ai_assistants",
        "tbl_ai_assistant_knowledge",
        "tbl_ai_assistant_chunks",
        "tbl_ai_assistant_message_meta",
        "tbl_ai_assistant_instruction_audit",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )

    # --- ALTER tbl_embed_keys ------------------------------------------------
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "resource_type",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'lead_form'"),
        ),
    )
    op.add_column(
        "tbl_embed_keys",
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_embed_keys_resource_type",
        "tbl_embed_keys",
        "resource_type IN ('lead_form', 'ai_assistant')",
    )
    op.create_index(
        "ix_embed_keys_resource",
        "tbl_embed_keys",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    # tbl_embed_keys ALTERs first — drop the CHECK + indexes + columns.
    op.execute("DROP INDEX IF EXISTS ix_embed_keys_resource")
    op.drop_constraint("ck_embed_keys_resource_type", "tbl_embed_keys", type_="check")
    op.drop_column("tbl_embed_keys", "resource_id")
    op.drop_column("tbl_embed_keys", "resource_type")

    # RLS + tables in FK-safe reverse order.
    for table in (
        "tbl_ai_assistant_instruction_audit",
        "tbl_ai_assistant_message_meta",
        "tbl_ai_assistant_chunks",
        "tbl_ai_assistant_knowledge",
        "tbl_ai_assistants",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_instruction_audit_assistant_changed")
    op.drop_table("tbl_ai_assistant_instruction_audit")

    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_message_meta_org_assistant_created")
    op.drop_table("tbl_ai_assistant_message_meta")

    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_chunks_knowledge")
    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_chunks_org_status")
    op.drop_table("tbl_ai_assistant_chunks")

    op.execute("DROP INDEX IF EXISTS ix_ai_assistant_knowledge_assistant_status")
    op.drop_table("tbl_ai_assistant_knowledge")

    op.execute("DROP INDEX IF EXISTS ix_ai_assistants_org_status")
    op.execute("DROP INDEX IF EXISTS uq_ai_assistants_org_lower_name")
    op.drop_table("tbl_ai_assistants")

    for enum_name in (
        "cost_status",
        "chunk_status",
        "knowledge_status",
        "knowledge_source_type",
        "ai_assistant_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    # ``conversation_channel`` cannot lose the ``ai_widget`` value on
    # downgrade — Postgres does not support ``ALTER TYPE ... DROP
    # VALUE``. Left in place; if a caller re-runs upgrade, the
    # ``IF NOT EXISTS`` on the ADD VALUE keeps it idempotent.
