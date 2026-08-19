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


@_shared_task(
    name="src.app.core.ai_assistants.tasks.retention_cleanup",
    # Every 6 hours — slow sweep of old messages.
    acks_late=True,
    max_retries=1,
)
def retention_cleanup() -> dict[str, Any]:
    """Delete messages older than ``assistant.retention_days`` (default 90,
    capped 400). Logs to ``tbl_gdpr_deletion_log`` for GDPR SAR compliance.

    Runs every 6 hours. Idempotent — re-runs don't delete twice (once a
    message is gone, the query won't find it again).
    """
    from src.app.core.ai_assistants.janitor import retention_cleanup as _cleanup

    outcome = asyncio.run(_cleanup())
    logger.info("retention_cleanup deleted=%d", outcome["deleted_count"])
    return outcome


@_shared_task(
    name="src.app.core.ai_assistants.tasks.reap_stuck_ingest",
    # Every 5 minutes — fast check for stalled workers.
    acks_late=True,
    max_retries=1,
)
def reap_stuck_ingest() -> dict[str, Any]:
    """Mark knowledge rows stuck in ``processing`` status (no heartbeat
    for > 15 minutes) as ``failed_stuck``. Cleans up orphan chunks.

    Runs every 5 minutes. Idempotent — same stuck row won't be re-marked
    (status is already changed).
    """
    from src.app.core.ai_assistants.janitor import reap_stuck_ingest as _reap

    outcome = asyncio.run(_reap())
    logger.info("reap_stuck_ingest marked_failed=%d", outcome["marked_failed_count"])
    return outcome


@_shared_task(
    name="src.app.core.ai_assistants.tasks.cleanup_orphan_chunks",
    # Every 1 hour — cleanup safety net for FK CASCADE drift.
    acks_late=True,
    max_retries=1,
)
def cleanup_orphan_chunks() -> dict[str, Any]:
    """Delete chunks whose parent knowledge row is gone. FK CASCADE should
    prevent orphans, but this is the belt-and-braces cleanup for manual
    DB edits or migration drift.

    Runs every 1 hour. Idempotent — already-deleted chunks won't be found.
    """
    from src.app.core.ai_assistants.janitor import cleanup_orphan_chunks as _cleanup

    outcome = asyncio.run(_cleanup())
    logger.info("cleanup_orphan_chunks deleted=%d", outcome["deleted_count"])
    return outcome


@_shared_task(
    name="src.app.core.ai_assistants.tasks.expire_embed_key_grace",
    # Every 1 hour — cleanup for revoked embed keys past grace period.
    acks_late=True,
    max_retries=1,
)
def expire_embed_key_grace() -> dict[str, Any]:
    """Hard-delete revoked embed keys whose grace period has elapsed
    (revoked_at + grace_days < now()). Idempotent — already-deleted keys
    stay gone.

    Runs every 1 hour alongside the other maintenance sweeps.
    """
    from src.app.core.ai_assistants.janitor import expire_embed_key_grace as _expire

    outcome = asyncio.run(_expire())
    logger.info("expire_embed_key_grace deleted=%d", outcome["deleted_count"])
    return outcome


@_shared_task(
    name="src.app.core.ai_assistants.tasks.reconcile_cost_outbox",
    # Every 5 minutes — reconcile pending LLM costs.
    acks_late=True,
    max_retries=1,
)
def reconcile_cost_outbox() -> dict[str, Any]:
    """For message_meta rows stuck in ``pending_llm_confirm`` for > 5 min:
    attempt reconciliation against OpenAI's usage API (if available) or
    mark as failed with a timeout error.

    v1 uses timeout-to-failed fallback; real usage-API integration is a
    follow-up step.

    Runs every 5 minutes. Idempotent — already-marked rows stay as-is.
    """
    from src.app.core.ai_assistants.janitor import reconcile_cost_outbox as _reconcile

    outcome = asyncio.run(_reconcile())
    logger.info(
        "reconcile_cost_outbox reconciled=%d failed=%d",
        outcome["reconciled_count"],
        outcome["failed_count"],
    )
    return outcome


@_shared_task(
    name="src.app.core.ai_assistants.tasks.janitor_heartbeat",
    # Every 1 minute — heartbeat for external monitoring.
    acks_late=True,
    max_retries=0,
)
def janitor_heartbeat() -> dict[str, Any]:
    """Upsert a row to ``tbl_janitor_heartbeats`` to signal the janitor
    beat scheduler is alive. External monitoring (Prometheus, etc.) checks
    if any task's last_run_at < now() - 48h and alerts if the heartbeat
    stops.

    Runs every 1 minute. Idempotent — same row is updated every time.
    """
    from src.app.core.ai_assistants.janitor import janitor_heartbeat as _hb

    outcome = asyncio.run(_hb())
    return outcome


__all__ = [
    "HAS_CELERY",
    "ingest_knowledge",
    "retention_cleanup",
    "reap_stuck_ingest",
    "cleanup_orphan_chunks",
    "expire_embed_key_grace",
    "reconcile_cost_outbox",
    "janitor_heartbeat",
]
