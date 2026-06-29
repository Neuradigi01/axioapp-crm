"""Celery tasks for the workflow execution engine.

Two tasks today:

  * :func:`process_step` — fires once per workflow hop. The engine
    re-enqueues itself between nodes (sequential / branch); wait
    nodes park the run with ``next_step_at`` set; the beat sweep
    re-dispatches the parked run when its time comes.
  * :func:`sweep_waits` — beat-scheduled every 60s. Pulls pending
    runs whose ``next_step_at <= now`` and dispatches
    :func:`process_step` for each.

Convention: ``@shared_task`` wrappers call ``asyncio.run(...)`` per
``src/celery/worker.py``'s engine-reset hooks. Don't write
``async def`` tasks — they can't be ``.delay()``'d.

Mirrors the celery-absent shim shape of
:mod:`core.automation.tasks` / :mod:`core.appointments.tasks` so
dev shells without Celery installed don't break import — the shim's
``apply_async`` is a no-op so the engine's
``process_step.apply_async(args=(run_id,))`` call still compiles
+ tests can monkey-patch the dispatch.
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
    name="src.app.core.workflows.tasks.process_step",
)
def process_step(run_id: str) -> dict[str, Any]:
    """One workflow hop. Loads the run, resolves + runs the current
    node's action handler, persists a step_run audit row, advances
    to the next node. Recursion via ``apply_async`` re-enqueue,
    never inline."""
    return asyncio.run(_process_step_async(run_id))


async def _process_step_async(run_id: str) -> dict[str, Any]:
    from src.app.core.workflows import engine

    return await engine.process_step(uuid.UUID(run_id))


@_shared_task(
    name="src.app.core.workflows.tasks.sweep_waits",
)
def sweep_waits() -> dict[str, int]:
    """Beat-scheduled (60s cadence). Pulls pending runs whose
    ``next_step_at <= now()`` and re-dispatches
    :func:`process_step` for each. The dispatcher's ``FOR UPDATE
    SKIP LOCKED`` row lock handles the case where the sweep fires
    while a worker is already processing the same run."""
    return asyncio.run(_sweep_waits_async())


async def _sweep_waits_async() -> dict[str, int]:
    from src.app.core.workflows import engine

    return await engine.resume_after_wait()


@_shared_task(
    name="src.app.core.workflows.tasks.expire_waits",
)
def expire_waits() -> dict[str, Any]:
    """Beat-scheduled every 2 minutes. Finds parked
    ``flow_control.wait_for_event`` waits whose ``expires_at <=
    now()`` + resumes each run on the ``timeout`` outbound edge,
    then deletes the wait row."""
    return asyncio.run(_expire_waits_async())


async def _expire_waits_async() -> dict[str, Any]:
    from src.app.core.workflows import (
        data_access as _wf_da,
        engine as _engine,
    )
    from src.app.shared.db import async_session

    resumed = 0
    deleted = 0
    failed = 0

    async with async_session() as session:
        expired = await _wf_da.list_expired_waits(session, limit=200)
        for wait in expired:
            # Delete first so a hair-late event publish doesn't
            # also resume the same wait.
            try:
                await _wf_da.delete_event_wait(session, wait)
                await session.commit()
                deleted += 1
            except Exception:
                logger.exception(
                    "workflows.expire_waits delete_failed wait=%s", wait.id
                )
                failed += 1
                continue

            try:
                await _engine.resume_run(
                    wait.run_id, output_edge_label="timeout"
                )
                resumed += 1
            except Exception:
                logger.exception(
                    "workflows.expire_waits resume_failed wait=%s run=%s",
                    wait.id,
                    wait.run_id,
                )
                failed += 1

    return {
        "found": len(expired),
        "deleted": deleted,
        "resumed": resumed,
        "failed": failed,
    }


__all__ = ["expire_waits", "process_step", "sweep_waits"]
