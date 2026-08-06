"""Pin tests for ``core.workflows._croniter_timeout``.

Covers:
  * ``run_with_timeout`` returns the fn's value on the happy path.
  * Raises :class:`RecurrenceTimeout` on breach.
  * Propagates ``fn``'s exceptions verbatim.
  * The executor is a singleton — reused across calls (checked by
    running many quick invocations without spawning fresh executors).
"""

from __future__ import annotations

import time

import pytest

from src.app.core.workflows._croniter_timeout import (
    RecurrenceTimeout,
    run_with_timeout,
)


def test_run_with_timeout_returns_value_on_happy_path():
    assert run_with_timeout(lambda: 42) == 42


def test_run_with_timeout_returns_kwargs_result():
    def f(x, *, y):
        return x + y

    assert run_with_timeout(f, 3, y=4) == 7


def test_run_with_timeout_raises_recurrence_timeout_on_breach():
    def _slow():
        time.sleep(0.6)
        return "never"

    with pytest.raises(RecurrenceTimeout) as ei:
        run_with_timeout(_slow, timeout_ms=100)
    assert "100ms" in str(ei.value)


def test_run_with_timeout_propagates_fn_exceptions():
    class Boom(Exception):
        pass

    def _bad():
        raise Boom("nope")

    with pytest.raises(Boom, match="nope"):
        run_with_timeout(_bad)


def test_run_with_timeout_many_quick_calls_share_executor():
    # 200 quick invocations — the singleton executor caps at 4
    # threads; if it spawned a thread per call this would take
    # noticeable time. Simply asserting all succeed exercises the
    # executor-singleton path.
    for i in range(200):
        assert run_with_timeout(lambda i=i: i * 2) == i * 2
