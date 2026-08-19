"""Celery task registration for the AI Assistants module.

One task today: :func:`ingest_knowledge` — dispatched from the
knowledge-upload endpoints in :mod:`.router` via
``ingest_knowledge.delay(str(knowledge_id))``.

Convention (matches :mod:`core.workflows.tasks`): the ``@shared_task``
wrapper is sync and calls ``asyncio.run(...)`` on the async
implementation in :mod:`.ingest`. Don't ``async def`` the wrapper —
Celery's ``.delay()`` can't dispatch coroutines.

Celery-absent shim: dev shells that don't install Celery still
import this module (e.g. via ``main.py`` autoloading task modules
for discovery); the shim's ``apply_async`` is a no-op so tests that
monkey-patch the dispatch or use ``.apply()`` for inline execution
still work.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover — celery absent in dev shells
    HAS_CELERY = False

    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply_async(self, args=None, kwargs=None, **_):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        return _wrap


logger = logging.getLogger(__name__)


@_shared_task(
    name="src.app.core.ai_assistants.tasks.ingest_knowledge",
    # Worker-hygiene: parser libs (pdfplumber, lxml) can leak native
    # memory across ingests; recycling the worker after each task
    # keeps residents bounded. Set in deploy config too.
    acks_late=True,
    max_retries=3,
)
def ingest_knowledge(knowledge_id: str) -> dict[str, Any]:
    """Kick off the ingest pipeline for one knowledge row.

    Returns a dict shape (not the :class:`IngestOutcome` dataclass)
    so Celery's default JSON serialiser can round-trip the result to
    the operator UI without a custom encoder.
    """
    outcome = asyncio.run(_ingest_async(knowledge_id))
    return {
        "knowledge_id": knowledge_id,
        "status": outcome.status,
        "chunk_count": outcome.chunk_count,
        "error": outcome.error,
    }


async def _ingest_async(knowledge_id: str):
    from src.app.core.ai_assistants import ingest as _ingest

    return await _ingest.ingest_knowledge(uuid.UUID(knowledge_id))


__all__ = ["HAS_CELERY", "ingest_knowledge"]
