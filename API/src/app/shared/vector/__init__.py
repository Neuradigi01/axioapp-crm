"""Vector store abstraction for the AI Assistants track.

Callers program to the :class:`VectorStore` protocol and get one
back via :func:`vector_store`. v1 has a single implementation —
:class:`~src.app.shared.vector.pgvector.PgVectorStore` — backed by
the ``pgvector`` Postgres extension installed in migration
``0200_install_pgvector``.

The interface is deliberately narrow (three methods: ``upsert`` /
``search`` / ``delete_by_parent``) so a future swap to Pinecone /
Weaviate / Qdrant is a single new adapter file, not a rewrite of
every caller.

Every method takes ``org_id`` explicitly. There is no ambient
"current org" — the AI ingest task (Step 10) runs inside a Celery
worker where no request context is set, and the retrieval query
(Step 9) runs during SSE streaming where the surrounding session
was opened before the context middleware fired. Passing the org
explicitly + setting ``app.current_org_id`` on the session for
RLS is the safe pattern.
"""

from __future__ import annotations

from src.app.shared.vector.base import (
    SearchResult,
    VectorEntry,
    VectorStore,
)
from src.app.shared.vector.chunker import Chunk, chunk_text


def vector_store():  # -> VectorStore  (kept unannotated to avoid the
    # circular-import shape of returning a protocol whose implementation
    # imports back into this module)
    """Return the default vector-store implementation (pgvector).

    Local import so the pgvector adapter's SQLAlchemy dependencies
    are not paid on every consumer's module load — matters for the
    Celery worker where hundreds of task modules import from
    ``shared/``.
    """
    from src.app.shared.vector.pgvector import PgVectorStore

    return PgVectorStore


__all__ = [
    "Chunk",
    "SearchResult",
    "VectorEntry",
    "VectorStore",
    "chunk_text",
    "vector_store",
]
