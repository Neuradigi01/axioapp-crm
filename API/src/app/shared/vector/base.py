"""``VectorStore`` protocol + shared dataclasses.

Every implementation (only pgvector in v1) accepts the same three
shapes:

  * :class:`VectorEntry` for ``upsert`` — one row per chunk. Metadata
    is JSON-shaped so the retrieval side can pull back arbitrary
    scaffold data (source name, page number, etc.) without a JOIN.

  * :class:`SearchResult` from ``search`` — id + cosine score + the
    same metadata + the parent knowledge row's id.

Both are ``frozen=True``, ``slots=True`` for cheap allocation and
no accidental mutation from a caller.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class VectorEntry:
    """One row to insert into the vector store.

    ``parent_id`` links back to the knowledge row (Step 5's
    ``tbl_ai_assistant_knowledge.id``) so a delete of the parent
    cascades chunks in one call to :meth:`VectorStore.delete_by_parent`.

    ``parent_type`` is a string discriminator (``'knowledge'`` in v1)
    that leaves room for future non-knowledge chunk sources without
    changing the schema.
    """

    id: uuid.UUID
    org_id: uuid.UUID
    embedding: Sequence[float]
    parent_id: uuid.UUID
    parent_type: str = "knowledge"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One result row from :meth:`VectorStore.search`.

    ``score`` is cosine similarity in ``[0, 1]`` — 1.0 = identical
    vectors. Implementations may return ``score`` derived from
    distance ( `1 - cosine_distance` ) so the caller gets a
    consistent higher-is-better ordering regardless of the
    underlying operator (``<=>`` for pgvector cosine distance,
    ``<->`` for L2, ``<#>`` for inner product).
    """

    id: uuid.UUID
    score: float
    parent_id: uuid.UUID
    metadata: dict[str, Any]


class VectorStore(Protocol):
    """The three-method surface every vector-store implementation
    must provide."""

    async def upsert(
        self,
        entries: Sequence[VectorEntry],
    ) -> None:
        """Insert or replace the given entries.

        Implementations write in one round-trip (pgvector uses
        ``INSERT ... ON CONFLICT (id) DO UPDATE`` so re-ingest of
        the same knowledge row overwrites the previous chunks
        atomically).

        ``org_id`` lives on each :class:`VectorEntry` — the method
        deliberately does not take a separate ``org_id`` argument
        because ingest of a batch that spans two orgs is always a
        bug the caller should surface before it hits the DB.
        """

    async def search(
        self,
        *,
        org_id: uuid.UUID,
        query_embedding: Sequence[float],
        top_k: int = 5,
        filter_parent_id: uuid.UUID | None = None,
    ) -> list[SearchResult]:
        """Return the top-K most similar entries in ``org_id``.

        RLS-scoped: the implementation MUST set
        ``SET LOCAL app.current_org_id = :org_id`` on the session
        before running the query so the tenant-isolation policy
        fires. Belt+braces on top of the explicit ``WHERE org_id``
        predicate.

        ``filter_parent_id`` narrows to a single knowledge row —
        used by preview / test flows that only want to check
        retrieval against a specific ingest.
        """

    async def delete_by_parent(
        self,
        *,
        org_id: uuid.UUID,
        parent_id: uuid.UUID,
        parent_type: str = "knowledge",
    ) -> int:
        """Delete every chunk belonging to a parent knowledge row.

        Returns the number of rows deleted. Used by Step 10's
        replace-in-place flow (delete v1 chunks after v2 finishes
        ingesting) and by the org-delete cascade in Step 17.
        """


__all__ = [
    "SearchResult",
    "VectorEntry",
    "VectorStore",
]
