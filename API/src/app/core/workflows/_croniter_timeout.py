"""500ms hard timeout wrapper around ``croniter.get_next`` and any
other pure-Python compute inside the schedule dispatch loop.

Why the wrapper is here (``tasks/workflow-scheduling`` Step 2):
    ``croniter`` versions have had CPU-pathological cases on some
    inputs, and the schedule sweep re-parses ``config_json`` on
    every load (a bypass-API mutation could plant a malformed
    expression). Without a timeout, one bad row on the beat thread
    would stall the sweep for every org.

Design:
    ``concurrent.futures.ThreadPoolExecutor`` gives portable, safe
    interruption of a purely CPU-bound function — ``signal.alarm``
    is UNIX-only and cannot be used inside the async event loop
    without breaking its own signal handling. A worker thread is
    the right primitive for this narrow "compute a datetime, ≤500ms"
    case; we accept the thread-spawn cost (~20µs) as cheap next to
    the 500ms budget itself. The executor is a module-level singleton
    reused across the whole sweep tick so we don't churn threads.

    ``future.result(timeout=…)`` raises :class:`TimeoutError` on
    breach — service layer catches → deactivates the schedule with
    ``deactivation_reason='recurrence_timeout'`` (per README locked
    decisions).

    We deliberately do NOT kill the worker thread on timeout — Python
    can't cancel arbitrary CPU work — instead we let the thread run
    to completion in the background and drop its result. The service
    still returns to the sweep loop within 500ms; the run-away
    computation self-terminates when croniter's own internal ceiling
    (never observed >2s in the wild) kicks in. Combined with the
    schedule-row deactivation, one bad row can waste at most one
    worker thread for a few seconds — not the whole sweep.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout

# One executor for the whole process. ``max_workers=4`` bounds the
# blast radius of pathological rows: the sweep processes up to 100
# schedules per tick sequentially, so 4 parallel timed-out workers
# is a very loose ceiling. Threads are lazy — the executor spawns
# them only when needed and reaps them after 60s idle.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wf-crontimeout")


DEFAULT_TIMEOUT_MS = 500


class RecurrenceTimeout(TimeoutError):
    """Raised when recurrence compute exceeds the hard timeout.

    Distinct class so the caller can pattern-match on it vs a plain
    :class:`TimeoutError` from unrelated I/O."""


def run_with_timeout[T](
    fn: Callable[..., T],
    /,
    *args: object,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    **kwargs: object,
) -> T:
    """Run ``fn(*args, **kwargs)`` with a hard timeout in ms.

    Raises :class:`RecurrenceTimeout` on breach; propagates any
    other exception ``fn`` raises.

    ``fn`` must be a pure-Python callable. NOT for coroutines — this
    thread-executor path would run the coroutine object without
    awaiting it. Async recurrence compute is unnecessary anyway;
    ``croniter.get_next`` is synchronous."""
    future = _EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout_ms / 1000.0)
    except _FutureTimeout as exc:
        raise RecurrenceTimeout(f"recurrence compute exceeded {timeout_ms}ms hard timeout") from exc


__all__ = [
    "DEFAULT_TIMEOUT_MS",
    "RecurrenceTimeout",
    "run_with_timeout",
]
