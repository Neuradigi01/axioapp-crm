"""End-to-end smoke test for :class:`PgVectorStore`.

Runs against the real Postgres the API container is wired to. Skips
cleanly when:

  * The DB env vars (DB_HOST etc.) are missing (dev running host
    Python without the compose stack up).
  * The ``vector`` extension isn't installed on the target DB.

Uses an ephemeral test table with the same shape as Step 5's
``tbl_ai_assistant_chunks`` so the SQL emitted by
``PgVectorStore.upsert`` / ``.search`` / ``.delete_by_parent`` runs
without needing Step 5 to have shipped. The test table drops at
the end so subsequent test runs are idempotent.

Also asserts that the RLS session variable IS set on each call by
snapshotting the SQL log via a SQLAlchemy event.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.app.shared.vector import VectorEntry
from src.app.shared.vector.pgvector import PgVectorStore

pytestmark = pytest.mark.asyncio


def _db_url() -> str | None:
    """Build the async DB URL from container env vars, or return
    None if any required piece is missing."""
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


_TEST_TABLE = "tbl_pgvector_smoke_test"


async def _extension_installed(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT 1 FROM pg_extension WHERE extname='vector'"),
    )
    return result.scalar_one_or_none() is not None


async def _drop_test_table(session: AsyncSession) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS {_TEST_TABLE}"))


async def _create_test_table(session: AsyncSession) -> None:
    """Same shape as Step 5's tbl_ai_assistant_chunks — minus the
    HNSW index (a b-tree scan on 5 rows is fine for the smoke)."""
    await session.execute(
        text(
            f"""
            CREATE TABLE {_TEST_TABLE} (
                id UUID PRIMARY KEY,
                org_id UUID NOT NULL,
                knowledge_id UUID NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding VECTOR(4) NOT NULL,
                token_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready'
            )
            """
        )
    )


class _SmokePgVectorStore(PgVectorStore):
    """Override the module-level constant so the test SQL points at
    our ephemeral table without touching the production one."""


async def _install_test_table_name(store_cls: type[PgVectorStore]) -> None:  # noqa: ARG001
    # We can't monkey-patch a module-level constant across an async
    # call chain cleanly, so instead of subclassing we rewrite the
    # constant on the module. Restored in the test's finally block.
    pass


@pytest.mark.asyncio
async def test_pgvector_smoke_upsert_search_delete() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set — pgvector smoke skipped")

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from src.app.shared.vector import pgvector as pv_module

    async with sessionmaker() as session:
        # Skip guard — extension is a deployment precondition (see
        # migration 0200 + README §Locked design 3).
        if not await _extension_installed(session):
            await engine.dispose()
            pytest.skip("pgvector extension not installed — smoke skipped")

        original_table = pv_module._CHUNKS_TABLE
        pv_module._CHUNKS_TABLE = _TEST_TABLE
        try:
            await _drop_test_table(session)
            await _create_test_table(session)
            await session.commit()

            # Fresh transaction so SET LOCAL applies to the whole test.
            async with session.begin():
                store = PgVectorStore(session)
                org_id = uuid.uuid4()
                knowledge_id = uuid.uuid4()

                # Deliberately non-adjacent vectors so cosine-distance
                # ordering is predictable and independent of DB flakiness.
                #   e1 = [1,0,0,0]  → most similar to query [0.99, 0.05, 0, 0]
                #   e2 = [0.9, 0.1, 0, 0]  → 2nd
                #   e3 = [0.1, 0.9, 0, 0]  → 3rd
                #   e4 = [0, 1, 0, 0]      → 4th
                #   e5 = [0, 0, 1, 0]      → 5th
                embeddings: list[list[float]] = [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.9, 0.1, 0.0, 0.0],
                    [0.1, 0.9, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ]
                ids = [uuid.uuid4() for _ in embeddings]
                await store.upsert(
                    [
                        VectorEntry(
                            id=ids[i],
                            org_id=org_id,
                            parent_id=knowledge_id,
                            embedding=embeddings[i],
                            metadata={
                                "chunk_index": i,
                                "text": f"chunk {i}",
                                "token_count": 4,
                            },
                        )
                        for i in range(len(embeddings))
                    ],
                )

                results = await store.search(
                    org_id=org_id,
                    query_embedding=[0.99, 0.05, 0.0, 0.0],
                    top_k=3,
                )
                assert len(results) == 3
                # Top result must be e1 (most aligned with the query).
                assert results[0].id == ids[0]
                # Second must be e2.
                assert results[1].id == ids[1]
                # Scores are similarity (higher = better) and monotone.
                assert results[0].score >= results[1].score >= results[2].score
                # e5 (orthogonal on the third axis) must NOT be in top 3.
                assert ids[4] not in {r.id for r in results}

                # Cross-org isolation: search under a different org
                # returns zero (RLS + WHERE org_id both fire).
                other_org = uuid.uuid4()
                cross = await store.search(
                    org_id=other_org,
                    query_embedding=[0.99, 0.05, 0.0, 0.0],
                    top_k=5,
                )
                assert cross == []

                # Delete-by-parent removes all rows.
                deleted = await store.delete_by_parent(
                    org_id=org_id,
                    parent_id=knowledge_id,
                )
                assert deleted == len(embeddings)

                # And a subsequent search returns empty.
                after = await store.search(
                    org_id=org_id,
                    query_embedding=[0.99, 0.05, 0.0, 0.0],
                    top_k=5,
                )
                assert after == []

            # Cleanup outside the transaction that has the temp state.
            await _drop_test_table(session)
            await session.commit()
        finally:
            pv_module._CHUNKS_TABLE = original_table
            await engine.dispose()


@pytest.mark.asyncio
async def test_search_emits_set_local_app_current_org_id() -> None:
    """Capture the SQL that ``search`` actually runs and assert the
    RLS session variable is set BEFORE the SELECT. Belt+braces on
    the ``WHERE org_id`` predicate — an implementation that
    dropped ``SET LOCAL`` while still filtering by org would still
    pass the isolation smoke above but silently break RLS for any
    consumer that relies on it (chatbot AI nodes in Step 9, for
    instance)."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set — pgvector smoke skipped")

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from src.app.shared.vector import pgvector as pv_module

    captured: list[str] = []

    def _capture(conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401, ARG001
        captured.append(statement)

    async with sessionmaker() as session:
        if not await _extension_installed(session):
            await engine.dispose()
            pytest.skip("pgvector extension not installed — smoke skipped")

        original_table = pv_module._CHUNKS_TABLE
        pv_module._CHUNKS_TABLE = _TEST_TABLE
        try:
            await _drop_test_table(session)
            await _create_test_table(session)
            await session.commit()

            # Register the capture hook on the underlying sync
            # connection.
            sync_engine = engine.sync_engine
            event.listen(sync_engine, "before_cursor_execute", _capture)

            async with session.begin():
                store = PgVectorStore(session)
                await store.search(
                    org_id=uuid.uuid4(),
                    query_embedding=[1.0, 0.0, 0.0, 0.0],
                    top_k=1,
                )

            event.remove(sync_engine, "before_cursor_execute", _capture)

            # Two SELECTs of interest: the set_config('app.current_org_id',...)
            # call (RLS session-var set), and the actual chunks
            # search (FROM the test table). The former MUST run
            # first so the tenant-isolation policy fires when the
            # search executes.
            set_config_idx = next(
                (i for i, s in enumerate(captured) if "set_config" in s and "app.current_org_id" in s),
                -1,
            )
            search_idx = next(
                (i for i, s in enumerate(captured) if _TEST_TABLE in s),
                -1,
            )
            assert set_config_idx >= 0, (
                f"set_config('app.current_org_id', ...) was not emitted. Captured: {captured}"
            )
            assert search_idx >= 0, (
                f"chunks-table SELECT was not emitted. Captured: {captured}"
            )
            assert set_config_idx < search_idx, (
                "set_config must precede the chunks-table SELECT — RLS would "
                "not apply otherwise"
            )

            await _drop_test_table(session)
            await session.commit()
        finally:
            pv_module._CHUNKS_TABLE = original_table
            await engine.dispose()
