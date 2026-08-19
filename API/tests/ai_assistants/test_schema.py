"""Import + registration + fanout sanity checks for the AI
Assistants schema.

Pure-Python where possible. DB-dependent assertions are guarded by
env-var checks so the tests skip when the compose stack isn't up.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _sync_db_url() -> str | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


# --- Model + enum imports -------------------------------------------------


def test_models_import() -> None:
    """Every model + enum importable from the module namespace."""
    from src.app.core.ai_assistants.models import (
        AiAssistant,
        AiAssistantChunk,
        AiAssistantInstructionAudit,
        AiAssistantKnowledge,
        AiAssistantMessageMeta,
        AiAssistantStatus,
        ChunkStatus,
        CostStatus,
        KnowledgeSourceType,
        KnowledgeStatus,
    )

    for model in (
        AiAssistant,
        AiAssistantChunk,
        AiAssistantInstructionAudit,
        AiAssistantKnowledge,
        AiAssistantMessageMeta,
    ):
        assert hasattr(model, "__tablename__")
        assert model.__tablename__.startswith("tbl_ai_assistant")

    assert AiAssistantStatus.draft.value == "draft"
    assert AiAssistantStatus.active.value == "active"
    assert AiAssistantStatus.archived.value == "archived"

    assert set(KnowledgeSourceType) == {
        KnowledgeSourceType.file,
        KnowledgeSourceType.text,
        KnowledgeSourceType.url,
    }

    assert {s.value for s in KnowledgeStatus} == {
        "pending",
        "processing",
        "ready",
        "failed_no_text",
        "failed_stuck",
        "failed_ingest",
        "pending_delete",
        "pending_cancel",
    }

    assert set(ChunkStatus) == {ChunkStatus.ready, ChunkStatus.pending_delete}
    assert {s.value for s in CostStatus} == {
        "pending_llm_confirm",
        "confirmed",
        "reconciled",
        "failed",
    }


def test_all_models_are_tenant_scoped() -> None:
    """Rule 2 audit: every table has ``org_id``."""
    from src.app.core.ai_assistants.models import (
        AiAssistant,
        AiAssistantChunk,
        AiAssistantInstructionAudit,
        AiAssistantKnowledge,
        AiAssistantMessageMeta,
    )
    from src.app.shared.orm import TenantScoped

    for model in (
        AiAssistant,
        AiAssistantChunk,
        AiAssistantInstructionAudit,
        AiAssistantKnowledge,
        AiAssistantMessageMeta,
    ):
        assert issubclass(model, TenantScoped), f"{model.__name__} must inherit TenantScoped"
        assert "org_id" in model.__table__.columns


def test_ai_assistant_has_optimistic_concurrency_wired() -> None:
    """``__mapper_args__.version_id_col`` set to the version column
    so SQLAlchemy manages the ++ on every UPDATE (Step 6 relies on
    this to raise StaleDataError → 409). Reads through the mapper
    itself rather than ``__mapper_args__`` because SQLAlchemy
    resolves the reference at mapper-construction time (post
    class-body), so the mapper is the source of truth."""
    from src.app.core.ai_assistants.models import AiAssistant

    mapper = AiAssistant.__mapper__
    assert mapper.version_id_col is AiAssistant.__table__.c.version
    # Default generator (integer increment) — NOT False (which would
    # mean "server-generated", i.e. no client-side bump).
    assert mapper.version_id_generator is not False
    assert callable(mapper.version_id_generator)


def test_message_meta_pk_is_message_id() -> None:
    """AiAssistantMessageMeta keyed on message_id (side-table on
    tbl_messages), not a synthetic id — the whole point of the side
    table is 1:1 with the message row."""
    from src.app.core.ai_assistants.models import AiAssistantMessageMeta

    pk_cols = list(AiAssistantMessageMeta.__table__.primary_key.columns)
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "message_id"


def test_chunks_embedding_column_is_vector() -> None:
    """Vector(1536) sized for OpenAI text-embedding-3-small."""
    from pgvector.sqlalchemy import Vector

    from src.app.core.ai_assistants.models import AiAssistantChunk

    embedding_col = AiAssistantChunk.__table__.c.embedding
    assert isinstance(embedding_col.type, Vector)
    assert embedding_col.type.dim == 1536


# --- Module descriptor ----------------------------------------------------


def test_module_descriptor_registers_between_workflows_and_chatbots() -> None:
    from src.app.core.ai_assistants.module import MODULE

    assert MODULE.id == "ai_assistants"
    assert MODULE.route == "/api/v1/ai-assistants"
    assert MODULE.frontend_route == "/user/ai-assistants"
    assert MODULE.section == "Automation"
    assert MODULE.menu_position == 715
    assert "ai_assistants.view" in MODULE.permissions
    assert "ai_assistants.manage" in MODULE.permissions


def test_permission_keys_registered() -> None:
    from src.app.core.ai_assistants.permissions import (
        ADMIN_KEYS,
        ALL_KEYS,
        EMPLOYEE_KEYS,
        OWNER_KEYS,
        PERM_MANAGE,
        PERM_VIEW,
    )

    assert PERM_VIEW == "ai_assistants.view"
    assert PERM_MANAGE == "ai_assistants.manage"
    assert set(ALL_KEYS) == {PERM_VIEW, PERM_MANAGE}
    assert OWNER_KEYS == ALL_KEYS
    assert ADMIN_KEYS == ALL_KEYS
    assert EMPLOYEE_KEYS == (PERM_VIEW,)


def test_role_templates_grant_keys_correctly() -> None:
    """Owner + Admin get both keys via _CORE_ADMIN_KEYS which
    _CORE_OWNER_KEYS extends; Employee gets only view."""
    from src.app.core.permissions import role_templates as rt

    for key in ("ai_assistants.view", "ai_assistants.manage"):
        assert key in rt._CORE_ADMIN_KEYS, f"{key} missing from Admin"
        assert key in rt._CORE_OWNER_KEYS, f"{key} missing from Owner"

    assert "ai_assistants.view" in rt._CORE_EMPLOYEE_KEYS
    assert "ai_assistants.manage" not in rt._CORE_EMPLOYEE_KEYS


# --- DB-dependent (skipped when compose stack down) ----------------------


def test_all_tables_have_rls_policies_installed() -> None:
    url = _sync_db_url()
    if not url:
        pytest.skip("DB env vars not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE tablename IN (
                      'tbl_ai_assistants',
                      'tbl_ai_assistant_knowledge',
                      'tbl_ai_assistant_chunks',
                      'tbl_ai_assistant_message_meta',
                      'tbl_ai_assistant_instruction_audit'
                    )
                    """
                )
            ).fetchall()
            found = {r[0] for r in rows}
            assert found == {
                "tbl_ai_assistants",
                "tbl_ai_assistant_knowledge",
                "tbl_ai_assistant_chunks",
                "tbl_ai_assistant_message_meta",
                "tbl_ai_assistant_instruction_audit",
            }, f"missing tables: {found}"

            policy_rows = conn.execute(
                text(
                    """
                    SELECT tablename, policyname FROM pg_policies
                    WHERE tablename LIKE 'tbl_ai_assistant%'
                    """
                )
            ).fetchall()
            policy_tables = {r[0] for r in policy_rows}
            assert policy_tables == found, f"tables without RLS policy: {found - policy_tables}"
    finally:
        engine.dispose()


def test_embed_keys_extension_backfilled() -> None:
    url = _sync_db_url()
    if not url:
        pytest.skip("DB env vars not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            # Every existing row got the default 'lead_form' via server_default.
            missing = conn.execute(
                text(
                    "SELECT COUNT(*) FROM tbl_embed_keys WHERE resource_type IS NULL"
                )
            ).scalar_one()
            assert missing == 0
            # CHECK constraint present.
            check_rows = conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conname = 'ck_embed_keys_resource_type'
                    """
                )
            ).fetchall()
            assert check_rows, "CHECK constraint ck_embed_keys_resource_type missing"
    finally:
        engine.dispose()


def test_conversation_channel_enum_has_ai_widget() -> None:
    url = _sync_db_url()
    if not url:
        pytest.skip("DB env vars not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT enumlabel FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'conversation_channel'
                    """
                )
            ).fetchall()
            labels = {r[0] for r in rows}
            assert "ai_widget" in labels, f"conversation_channel missing 'ai_widget'; got {labels}"
    finally:
        engine.dispose()


def test_hnsw_index_present() -> None:
    url = _sync_db_url()
    if not url:
        pytest.skip("DB env vars not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'tbl_ai_assistant_chunks'
                      AND indexname = 'ix_ai_assistant_chunks_embedding_hnsw'
                    """
                )
            ).fetchall()
            assert rows, "HNSW index missing on tbl_ai_assistant_chunks.embedding"
    finally:
        engine.dispose()


def test_permission_fanout_applied() -> None:
    """Backfill migration 0202 fanned out view/manage to Owner+Admin,
    view-only to Employee, on every existing org."""
    url = _sync_db_url()
    if not url:
        pytest.skip("DB env vars not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT p.key, r.name, COUNT(*) AS n
                    FROM tbl_role_permissions rp
                    JOIN tbl_roles r ON rp.role_id = r.id
                    JOIN tbl_permissions p ON rp.permission_id = p.id
                    WHERE p.key IN ('ai_assistants.view', 'ai_assistants.manage')
                    GROUP BY p.key, r.name
                    ORDER BY p.key, r.name
                    """
                )
            ).fetchall()
            grants = {(k, r): int(n) for (k, r, n) in rows}
            # Every org has Owner + Admin + Employee (dev DB may have
            # 40+ orgs from Steps 1–4). We only care that grants exist.
            assert grants.get(("ai_assistants.view", "Owner"), 0) > 0
            assert grants.get(("ai_assistants.view", "Admin"), 0) > 0
            assert grants.get(("ai_assistants.view", "Employee"), 0) > 0
            assert grants.get(("ai_assistants.manage", "Owner"), 0) > 0
            assert grants.get(("ai_assistants.manage", "Admin"), 0) > 0
            # Employee must NOT have `manage` by default.
            assert grants.get(("ai_assistants.manage", "Employee"), 0) == 0, (
                "Employee should NOT hold ai_assistants.manage by default"
            )
    finally:
        engine.dispose()


# --- Guard: no random-org context bleeding into TenantScoped filter ------


def test_uuid_module_available_in_models() -> None:
    """Regression against a lint sweep that removes the `uuid` import
    once the direct `uuid.UUID` type annotations are converted to
    string-based ones — the mapped_column typing still needs it at
    runtime."""
    import uuid as _uuid

    from src.app.core.ai_assistants.models import AiAssistant

    _ = _uuid.uuid4()
    assert AiAssistant.__table__.c.id.type.python_type is _uuid.UUID
