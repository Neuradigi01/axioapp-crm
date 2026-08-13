"""Celery tasks for the chatbot execution engine
(``tasks/chatbot-builder`` Step 6).

Mirrors the shape of :mod:`core.workflows.tasks` — thin sync wrappers
that call ``asyncio.run(engine._foo_async(...))``. Never write
``async def`` tasks — they can't be ``.delay()``'d under Celery.

Two tasks today:

  * :func:`process_step` — fires once per engine hop. The engine
    re-enqueues itself between nodes; wait-parked runs are woken by
    the trigger matcher on the next inbound (Step 5 hook) or by
    :func:`sweep_delay_resumes` for time-parked runs.

  * :func:`sweep_test_runs` — beat-scheduled hourly. Deletes
    ``is_test=true`` runs older than 24h so the test-fire endpoint
    (Case #22 / Decision §17) doesn't pollute run history forever.

Delay-park sweep (Step 9's ``delay`` node) will hang off
:mod:`core.workflows.tasks.sweep_waits` — the two engines share the
same 60s beat cadence rather than adding a second one. Step 9 wires
that hook when the delay handler lands.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
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
    name="src.app.core.chatbots.tasks.process_step",
)
def process_step(run_id: str) -> dict[str, Any]:
    """One engine hop. Loads the run, runs the current node's
    handler, persists a step-run audit row, advances / parks /
    completes. Recursion via ``apply_async`` re-enqueue, never
    inline."""
    return asyncio.run(_process_step_async(run_id))


async def _process_step_async(run_id: str) -> dict[str, Any]:
    from src.app.core.chatbots import engine

    return await engine.process_step(uuid.UUID(run_id))


@_shared_task(
    name="src.app.core.chatbots.tasks.sweep_chatbot_waits",
)
def sweep_chatbot_waits() -> dict[str, int]:
    """Beat-scheduled (every 60s). Picks up parked chatbot runs whose
    ``next_step_at <= now()`` and re-dispatches
    :func:`process_step` via ``engine.resume_run``.

    Handles two park kinds transparently:
      * ``("delay", node_id)``  → resumed_by='delay_expired'
      * ``("reply", conv_id)``  → resumed_by='timeout' (Ask-* 22h)
    """
    return asyncio.run(_sweep_chatbot_waits_async())


async def _sweep_chatbot_waits_async() -> dict[str, int]:
    from sqlalchemy import select

    from src.app.core.chatbots import engine
    from src.app.core.chatbots.models import ChatbotRun
    from src.app.shared.db import async_session

    now_ts = datetime.now(UTC)
    resumed = 0
    errored = 0

    async with async_session() as session:
        stmt = (
            select(ChatbotRun)
            .where(
                ChatbotRun.status == "parked",
                ChatbotRun.next_step_at.is_not(None),
                ChatbotRun.next_step_at <= now_ts,
                ChatbotRun.is_test.is_(False),
            )
            .limit(200)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for run in rows:
            park_key = (run.context or {}).get("park_key") or []
            resume_kind = "delay_expired"
            if isinstance(park_key, list) and park_key and park_key[0] == "reply":
                resume_kind = "timeout"
            try:
                await engine.resume_run(
                    session,
                    run_id=run.id,
                    resume_event={"_resumed_by": resume_kind},
                )
                resumed += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "chatbots.sweep_chatbot_waits failed run=%s", run.id
                )
                errored += 1

    if resumed or errored:
        logger.info(
            "chatbots.sweep_chatbot_waits resumed=%d errored=%d cutoff=%s",
            resumed,
            errored,
            now_ts,
        )
    return {"resumed": resumed, "errored": errored}


@_shared_task(
    name="src.app.core.chatbots.tasks.sweep_test_runs",
)
def sweep_test_runs() -> dict[str, int]:
    """Beat-scheduled (hourly). Deletes ``is_test=true`` chatbot
    runs older than 24h. Uses the partial index
    ``ix_chatbot_runs_test_sweep WHERE is_test=true`` (Step 1)."""
    return asyncio.run(_sweep_test_runs_async())


async def _sweep_test_runs_async() -> dict[str, int]:
    from sqlalchemy import delete

    from src.app.core.chatbots.models import ChatbotRun
    from src.app.shared.db import async_session

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    async with async_session() as session:
        try:
            result = await session.execute(
                delete(ChatbotRun).where(
                    ChatbotRun.is_test.is_(True),
                    ChatbotRun.started_at < cutoff,
                )
            )
            deleted = int(result.rowcount or 0)
            await session.commit()
        except Exception:
            logger.exception("chatbots.sweep_test_runs failed")
            await session.rollback()
            return {"deleted": 0, "errored": 1}

    if deleted:
        logger.info("chatbots.sweep_test_runs deleted=%d cutoff=%s", deleted, cutoff)
    return {"deleted": deleted}
