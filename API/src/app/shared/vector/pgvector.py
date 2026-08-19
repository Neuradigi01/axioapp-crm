"""``pgvector``-backed implementation of :class:`VectorStore`.

Uses raw SQL with parameterised bindings — the ``pgvector.psycopg``
/ ``pgvector.asyncpg`` adapters register the ``vector`` type on
the driver so passing a Python list of floats works transparently
in ``:param`` positions.

RLS: every call sets ``SET LOCAL app.current_org_id = :org_id`` on
the caller's session before running the actual query so the
tenant-isolation policy from Step 5's migration fires. The
``WHERE org_id = :org_id`` predicate on top is belt+braces (and
also lets the composite ``(org_id, status)`` index kick in).

Search operator: ``<=>`` is pgvector's cosine-distance operator
(0 = identical, 2 = opposite). We convert to a
higher-is-better similarity via ``1 - (embedding <=> :q)`` so the
:class:`~src.app.shared.vector.base.SearchResult.score` matches
the interface's contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.vector.base import SearchResult, VectorEntry


# The chunks table lives at ``tbl_ai_assistant_chunks`` and is
# owned by Step 5. Centralised here so a future rename (e.g. to
# accommodate a second vector-source table) is a one-line change
# rather than a grep-and-replace across every SQL literal.
_CHUNKS_TABLE = "tbl_ai_assistant_chunks"


class PgVectorStore:
    """pgvector implementation. One instance per :class:`AsyncSession`.

    The session is not owned — the caller (typically Step 9's chat
    runtime or Step 10's ingest task) opens + commits the
    surrounding transaction. This class stages statements only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- helpers ---------------------------------------------------

    async def _set_org_context(self, org_id: uuid.UUID) -> None:
        """Set the RLS session variable for the current transaction.

        Uses ``set_config('name', value, is_local=true)`` rather than
        the ``SET LOCAL`` DDL form because Postgres does not accept
        bind parameters on ``SET`` — the asyncpg driver would
        translate ``$1`` to a syntax error. ``set_config`` is
        parameterised, safe against injection, and semantically
        identical to ``SET LOCAL`` when the third arg is ``true``.
        """
        await self._session.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )

    @staticmethod
    def _vec_literal(embedding: Sequence[float]) -> str:
        """Format a Python list as pgvector's textual VECTOR literal
        (``'[0.1, 0.2, ...]'``). Used when binding through
        SQLAlchemy without the async adapter's type registration
        available — pgvector accepts the string form via implicit
        cast in ``INSERT`` and ``ORDER BY`` positions."""
        return "[" + ",".join(f"{float(x):.7f}" for x in embedding) + "]"

    # --- interface -------------------------------------------------

    async def upsert(self, entries: Sequence[VectorEntry]) -> None:
        if not entries:
            return
        # One org per batch — a mixed batch is always a caller bug.
        org_ids = {e.org_id for e in entries}
        if len(org_ids) != 1:
            raise ValueError(
                f"upsert batch spans {len(org_ids)} orgs; "
                "every VectorEntry in a batch must share the same org_id"
            )
        (org_id,) = org_ids
        await self._set_org_context(org_id)

        # Build the multi-row INSERT via executemany semantics — one
        # network round-trip. ON CONFLICT (id) DO UPDATE handles the
        # re-ingest case (Step 10's replace flow).
        stmt = text(
            f"""
            INSERT INTO {_CHUNKS_TABLE}
                (id, org_id, knowledge_id, chunk_index, text, embedding, token_count, status)
            VALUES (
                :id, :org_id, :parent_id, :chunk_index, :text,
                (:embedding_text)::vector, :token_count, 'ready'
            )
            ON CONFLICT (id) DO UPDATE SET
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding,
                token_count = EXCLUDED.token_count,
                status = 'ready'
            """
        )
        rows = [
            {
                "id": str(e.id),
                "org_id": str(e.org_id),
                "parent_id": str(e.parent_id),
                "chunk_index": int(e.metadata.get("chunk_index", 0)),
                "text": str(e.metadata.get("text", "")),
                "embedding_text": self._vec_literal(e.embedding),
                "token_count": int(e.metadata.get("token_count", 0)),
            }
            for e in entries
        ]
        await self._session.execute(stmt, rows)

    async def search(
        self,
        *,
        org_id: uuid.UUID,
        query_embedding: Sequence[float],
        top_k: int = 5,
        filter_parent_id: uuid.UUID | None = None,
    ) -> list[SearchResult]:
        await self._set_org_context(org_id)

        where_extra = "AND knowledge_id = :parent_id" if filter_parent_id else ""
        stmt = text(
            f"""
            SELECT
                id,
                knowledge_id AS parent_id,
                text,
                token_count,
                chunk_index,
                1 - (embedding <=> (:q)::vector) AS score
            FROM {_CHUNKS_TABLE}
            WHERE org_id = :org_id
              AND status = 'ready'
              {where_extra}
            ORDER BY embedding <=> (:q)::vector
            LIMIT :k
            """
        )
        params: dict[str, Any] = {
            "org_id": str(org_id),
            "q": self._vec_literal(query_embedding),
            "k": int(top_k),
        }
        if filter_parent_id is not None:
            params["parent_id"] = str(filter_parent_id)
        result = await self._session.execute(stmt, params)
        rows = result.mappings().all()
        return [
            SearchResult(
                id=uuid.UUID(str(r["id"])),
                score=float(r["score"]),
                parent_id=uuid.UUID(str(r["parent_id"])),
                metadata={
                    "text": r["text"],
                    "token_count": r["token_count"],
                    "chunk_index": r["chunk_index"],
                },
            )
            for r in rows
        ]

    async def delete_by_parent(
        self,
        *,
        org_id: uuid.UUID,
        parent_id: uuid.UUID,
        parent_type: str = "knowledge",  # noqa: ARG002 — kept for interface parity
    ) -> int:
        await self._set_org_context(org_id)
        stmt = text(
            f"""
            DELETE FROM {_CHUNKS_TABLE}
            WHERE org_id = :org_id
              AND knowledge_id = :parent_id
            """
        )
        result = await self._session.execute(
            stmt,
            {"org_id": str(org_id), "parent_id": str(parent_id)},
        )
        return int(result.rowcount or 0)


# Suppress unused-import warning for bindparam in some linters — kept
# available for future callers that need explicitly-typed params.
_ = bindparam


__all__ = ["PgVectorStore"]
