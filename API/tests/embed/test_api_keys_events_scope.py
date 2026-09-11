"""Migration + model contract for ``tasks/custom-events`` Step 1.

Additive column set on ``tbl_embed_keys`` + extended ``resource_type``
CHECK constraint. Pure-Python model check + DB-dependent assertions
guarded by env-var check (skip when compose stack isn't up), matching
the pattern in ``tests/ai_assistants/test_schema.py``.
"""

from __future__ import annotations

import os

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


# --- Model (pure Python) --------------------------------------------------


def test_embed_key_model_exposes_new_columns() -> None:
    """New columns added in migration 0224 are declared on the ORM
    model so downstream callers can read/write them without raw SQL."""
    from src.app.core.embed.models import EmbedKey

    expected = {
        "auto_create_contacts",
        "default_owner_user_id",
        "hmac_required",
        "mode",
        "key_lookup_hash",
        "old_key_hash",
        "old_key_expires_at",
        "hmac_secret_encrypted",
        "rate_limit_per_minute",
    }
    declared = {c.name for c in EmbedKey.__table__.columns}
    missing = expected - declared
    assert not missing, f"EmbedKey model missing columns from 0224: {missing}"


def test_embed_key_model_new_columns_have_expected_python_types() -> None:
    """Type check the model declarations match the migration DDL —
    catches accidental drift (e.g. someone edits the model to use
    Integer when the column is Boolean)."""
    from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text
    from sqlalchemy.dialects.postgresql import UUID

    from src.app.core.embed.models import EmbedKey

    cols = {c.name: c.type for c in EmbedKey.__table__.columns}

    assert isinstance(cols["auto_create_contacts"], Boolean)
    assert isinstance(cols["default_owner_user_id"], UUID)
    assert isinstance(cols["hmac_required"], Boolean)
    assert isinstance(cols["mode"], String) and cols["mode"].length == 4
    assert isinstance(cols["key_lookup_hash"], LargeBinary)
    assert isinstance(cols["old_key_hash"], Text)
    assert isinstance(cols["old_key_expires_at"], DateTime)
    assert isinstance(cols["hmac_secret_encrypted"], LargeBinary)
    assert isinstance(cols["rate_limit_per_minute"], Integer)


# --- DB-dependent (skip if compose stack not up) --------------------------


@pytest.fixture(scope="module")
def sync_engine():
    url = _sync_db_url()
    if url is None:
        pytest.skip("DB env vars not set — compose stack isn't up")
    eng = create_engine(url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


def test_columns_exist_with_expected_defaults(sync_engine) -> None:
    """Migration up applied → each new column present with expected
    default. Runs a metadata query, not a fixture insert."""
    query = text(
        """
        SELECT column_name, column_default, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_name = 'tbl_embed_keys'
          AND column_name IN (
            'auto_create_contacts',
            'default_owner_user_id',
            'hmac_required',
            'mode',
            'key_lookup_hash',
            'old_key_hash',
            'old_key_expires_at',
            'hmac_secret_encrypted',
            'rate_limit_per_minute'
          )
        """
    )
    with sync_engine.connect() as conn:
        rows = {r.column_name: r for r in conn.execute(query)}

    assert len(rows) == 9, f"Expected 9 new columns, got {sorted(rows)}"

    assert rows["auto_create_contacts"].column_default == "true"
    assert rows["auto_create_contacts"].is_nullable == "NO"
    assert rows["auto_create_contacts"].data_type == "boolean"

    assert rows["default_owner_user_id"].is_nullable == "YES"
    assert rows["default_owner_user_id"].data_type == "uuid"

    assert rows["hmac_required"].column_default == "false"
    assert rows["hmac_required"].is_nullable == "NO"

    assert rows["mode"].column_default == "'live'::character varying"
    assert rows["mode"].is_nullable == "NO"

    assert rows["key_lookup_hash"].is_nullable == "YES"
    assert rows["key_lookup_hash"].data_type == "bytea"

    assert rows["rate_limit_per_minute"].column_default == "100"
    assert rows["rate_limit_per_minute"].is_nullable == "NO"


def test_check_constraint_accepts_all_three_resource_types(sync_engine) -> None:
    """The extended CHECK now accepts ``events`` alongside the existing
    ``lead_form`` / ``ai_assistant`` values. Metadata query — doesn't
    write any rows."""
    query = text(
        """
        SELECT pg_get_constraintdef(oid) AS defn
        FROM pg_constraint
        WHERE conname = 'ck_embed_keys_resource_type'
        """
    )
    with sync_engine.connect() as conn:
        row = conn.execute(query).fetchone()

    assert row is not None, "ck_embed_keys_resource_type constraint missing"
    defn = row.defn
    assert "lead_form" in defn
    assert "ai_assistant" in defn
    assert "events" in defn, f"CHECK didn't gain 'events' value: {defn}"


def test_mode_check_constraint_present(sync_engine) -> None:
    """New ``ck_embed_keys_mode`` CHECK restricts ``mode`` to
    ``live`` / ``test``."""
    query = text(
        """
        SELECT pg_get_constraintdef(oid) AS defn
        FROM pg_constraint
        WHERE conname = 'ck_embed_keys_mode'
        """
    )
    with sync_engine.connect() as conn:
        row = conn.execute(query).fetchone()

    assert row is not None, "ck_embed_keys_mode constraint missing"
    assert "live" in row.defn
    assert "test" in row.defn


def test_lookup_hash_index_is_partial_unique(sync_engine) -> None:
    """``ix_embed_keys_lookup_hash`` is a partial UNIQUE index — the
    partial predicate matters because pre-Step-4 rows have NULL
    ``key_lookup_hash`` and a full UNIQUE would refuse them."""
    query = text(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE indexname = 'ix_embed_keys_lookup_hash'
        """
    )
    with sync_engine.connect() as conn:
        row = conn.execute(query).fetchone()

    assert row is not None, "ix_embed_keys_lookup_hash missing"
    idxdef = row.indexdef
    assert "UNIQUE" in idxdef, f"Not a unique index: {idxdef}"
    assert "key_lookup_hash IS NOT NULL" in idxdef, f"Not partial: {idxdef}"
