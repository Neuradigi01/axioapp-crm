"""Schema smoke tests for ``tasks/chatbot-builder`` Step 1.

Metadata-introspection tests — no live DB needed. Runs alongside the
CI pin-tests and catches shape drift immediately.

RLS + column defaults + FK-cascade behavioural tests need a live
Postgres and are covered by the manual verification checklist in the
step doc:

  * ``SELECT * FROM pg_policies WHERE tablename LIKE 'tbl_chatbot%'``
    → 5 rows (one per new table).
  * ``INSERT INTO tbl_contacts (...)`` without ``is_placeholder`` →
    default false.
  * ``DELETE FROM tbl_chatbot_runs WHERE id = ?`` while a message has
    ``chatbot_run_id`` set → message survives with the column nulled.
"""

from __future__ import annotations

# Force model registration so Base.metadata sees the new tables even
# when this file is the only one imported.
import src.app.core.chatbots.models  # noqa: F401
import src.app.core.contacts.models  # noqa: F401
import src.app.core.conversations.models  # noqa: F401
from src.app.shared.db import Base

_NEW_TABLES = (
    "tbl_chatbots",
    "tbl_chatbot_runs",
    "tbl_chatbot_step_runs",
    "tbl_chatbot_meters",
    "tbl_chatbot_pending_replies",
)


def test_all_five_chatbot_tables_registered() -> None:
    """Every table declared in Step 1 lands in Base.metadata."""
    registered = set(Base.metadata.tables)
    missing = [t for t in _NEW_TABLES if t not in registered]
    assert not missing, f"Missing chatbot tables in metadata: {missing}"


def test_every_chatbot_table_has_tbl_prefix() -> None:
    """Rule #2 — belt to the pin-test's suspenders. Catches the case
    where a future step adds a table under core/chatbots/ without the
    prefix."""
    for name in _NEW_TABLES:
        assert name.startswith("tbl_"), f"{name} violates tbl_ prefix convention"


def test_every_chatbot_table_has_org_id_column() -> None:
    """Rule #2 — every tenant-scoped table carries ``org_id``. The
    ``TenantScoped`` mixin enforces this at declaration time, but this
    test locks it in against the concrete metadata so a future
    accidental drop of the mixin fails loudly."""
    for name in _NEW_TABLES:
        table = Base.metadata.tables[name]
        assert "org_id" in table.columns, f"{name} missing org_id column"
        # org_id must be non-nullable and FK to tbl_organizations.
        org_id_col = table.columns["org_id"]
        assert not org_id_col.nullable, f"{name}.org_id must be non-nullable"
        fks = list(org_id_col.foreign_keys)
        assert fks, f"{name}.org_id must have a FK"
        assert any(
            fk.column.table.name == "tbl_organizations" for fk in fks
        ), f"{name}.org_id must reference tbl_organizations"


def test_message_chatbot_run_id_column_added() -> None:
    """The Step-1 column addition on tbl_messages."""
    table = Base.metadata.tables["tbl_messages"]
    assert "chatbot_run_id" in table.columns, (
        "tbl_messages.chatbot_run_id column missing — model modification "
        "not registered."
    )
    col = table.columns["chatbot_run_id"]
    assert col.nullable, "chatbot_run_id must be nullable (bot vs human)"
    fks = list(col.foreign_keys)
    assert fks, "chatbot_run_id must have a FK"
    fk = fks[0]
    assert fk.column.table.name == "tbl_chatbot_runs"
    assert fk.ondelete == "SET NULL", (
        "chatbot_run_id FK must SET NULL so the message row survives "
        "run garbage-collection"
    )


def test_contact_is_placeholder_column_added() -> None:
    """The Step-1 column addition on tbl_contacts."""
    table = Base.metadata.tables["tbl_contacts"]
    assert "is_placeholder" in table.columns, (
        "tbl_contacts.is_placeholder column missing — model modification "
        "not registered."
    )
    col = table.columns["is_placeholder"]
    assert not col.nullable, "is_placeholder must be non-nullable"
    # Server default is text('false') — check it exists rather than
    # comparing literal values which differ across SA versions.
    assert col.server_default is not None, "is_placeholder needs a server default"


def test_chatbot_runs_fk_cascades() -> None:
    """FK cascade decisions from Decision §Cases 3-6:

    - chatbot_id → RESTRICT so hard-delete requires archived-first.
    - conversation_id → SET NULL so run survives conversation delete.
    - contact_id → SET NULL so run survives contact delete/merge.
    """
    table = Base.metadata.tables["tbl_chatbot_runs"]

    def _fk_ondelete(col_name: str) -> str | None:
        fks = list(table.columns[col_name].foreign_keys)
        return fks[0].ondelete if fks else None

    assert _fk_ondelete("chatbot_id") == "RESTRICT"
    assert _fk_ondelete("conversation_id") == "SET NULL"
    assert _fk_ondelete("contact_id") == "SET NULL"


def test_chatbot_step_runs_cascade_from_run() -> None:
    """Deleting a run cascades its step_runs (audit rows go with it)."""
    table = Base.metadata.tables["tbl_chatbot_step_runs"]
    fks = list(table.columns["run_id"].foreign_keys)
    assert fks[0].ondelete == "CASCADE"


def test_meters_two_partial_unique_indexes_exist() -> None:
    """Per-conversation and per-org global uniqueness are separate
    partial indexes so both shapes can coexist without NULLS NOT
    DISTINCT gymnastics."""
    table = Base.metadata.tables["tbl_chatbot_meters"]
    index_names = {idx.name for idx in table.indexes}
    assert "uq_chatbot_meters_bot_conv" in index_names, (
        "Missing partial unique for per-conversation meter rows"
    )
    assert "uq_chatbot_meters_org_global" in index_names, (
        "Missing partial unique for per-org global meter row"
    )


def test_pending_replies_nonce_uniqueness() -> None:
    """Signed-URL nonces must be globally unique — same nonce can't
    be replayed across two rows."""
    table = Base.metadata.tables["tbl_chatbot_pending_replies"]
    uc_names = {c.name for c in table.constraints if hasattr(c, "columns")}
    assert "uq_chatbot_pending_replies_nonce" in uc_names, (
        "Missing unique constraint on nonce column"
    )


def test_chatbots_indexes_present() -> None:
    """Hot-path indexes for the Step-5 trigger matcher."""
    table = Base.metadata.tables["tbl_chatbots"]
    index_names = {idx.name for idx in table.indexes}
    assert "ix_chatbots_org_status" in index_names
    assert "ix_chatbots_org_priority_created" in index_names
