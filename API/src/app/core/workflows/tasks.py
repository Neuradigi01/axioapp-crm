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


# ---------------------------------------------------------------------------
# evaluate_ab_winners — Step 18
# ---------------------------------------------------------------------------


@_shared_task(
    name="src.app.core.workflows.tasks.evaluate_ab_winners",
)
def evaluate_ab_winners() -> dict[str, Any]:
    """Beat-scheduled hourly. Picks paired workflows whose
    ``ab_test_holdback_until <= now()`` AND whose
    ``ab_test_decided_at IS NULL``; for each pair, calls
    :func:`core.workflows.ab_testing.evaluate_pair_for_decision` which
    either auto-promotes the winner (decisive) or extends the
    holdback by 50% (inconclusive).

    Cross-tenant — opens a DB session WITHOUT a tenant context so
    the partial index sweep returns every org's due pairs in one
    pass. Notifications to the workflow owner are emitted via
    :mod:`core.notifications.service.notify` on the decisive path.
    """
    return asyncio.run(_evaluate_ab_winners_async())


async def _evaluate_ab_winners_async() -> dict[str, Any]:
    from src.app.core.workflows import ab_testing
    from src.app.shared.db import async_session

    decisions = 0
    extensions = 0
    errors = 0

    async with async_session() as session:
        pairs = await ab_testing.list_pairs_due_for_decision(session)
        for wf in pairs:
            try:
                outcome = await ab_testing.evaluate_pair_for_decision(
                    session, workflow=wf
                )
                await session.commit()
                if outcome.get("status") == "decided":
                    decisions += 1
                    await _notify_ab_decision(session, workflow=wf, outcome=outcome)
                elif outcome.get("status") == "extended":
                    extensions += 1
            except Exception:
                logger.exception(
                    "workflows.evaluate_ab_winners failed workflow=%s", wf.id
                )
                errors += 1
                try:
                    await session.rollback()
                except Exception:
                    pass

    return {
        "checked": len(pairs),
        "decided": decisions,
        "extended": extensions,
        "errors": errors,
    }


async def _notify_ab_decision(session, *, workflow, outcome: dict[str, Any]) -> None:
    """Best-effort notification to the workflow owner. Failures are
    swallowed — the auto-promote has already landed; a missed
    notification shouldn't roll it back."""
    try:
        from src.app.core.notifications import service as notifications_service
    except Exception:
        return
    owner_id = workflow.created_by_user_id
    if owner_id is None:
        return
    result = outcome.get("result", {})
    a_rate = result.get("a_rate", 0)
    b_rate = result.get("b_rate", 0)
    winner_id = outcome.get("winner_workflow_id")
    try:
        await notifications_service.notify(
            session,
            org_id=workflow.org_id,
            user_id=owner_id,
            title="A/B test decided",
            body=(
                f"Workflow '{workflow.name}' A/B test concluded: "
                f"winner={'A' if str(workflow.id) == winner_id else 'B'} "
                f"(a={a_rate:.1%} b={b_rate:.1%})."
            ),
        )
    except Exception:
        logger.exception(
            "workflows.evaluate_ab_winners notify_failed workflow=%s",
            workflow.id,
        )


__all__ = [
    "evaluate_ab_winners",
    "expire_waits",
    "process_step",
    "sweep_waits",
]
