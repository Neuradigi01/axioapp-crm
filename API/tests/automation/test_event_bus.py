"""Pin tests for the Step-1 event bus.

Covers the in-process pub/sub mechanics:
  * ``subscribe`` then ``publish`` invokes the handler with the
    envelope (caller payload + org_id + event_type).
  * Multiple subscribers on the same event each fire.
  * Subscribing for an unknown event type is allowed (forward-
    compatible) — handler simply never fires until something
    publishes.
  * A handler raising doesn't poison the next handler — the
    publisher's transaction completes regardless.
  * The taxonomy strings documented in ``bus.py`` are loose by
    design (any string accepted) so origin modules can publish
    forward-compatible events before consumers exist.
"""
from __future__ import annotations

import uuid

import pytest

from src.app.core.events import bus


pytestmark = pytest.mark.asyncio


def _reset():
    bus._clear_subscribers_for_tests()


async def test_subscribe_publish_invokes_handler_with_envelope():
    _reset()
    received: list[dict] = []

    async def handler(envelope):
        received.append(envelope)

    bus.subscribe("test.event", handler)

    org_id = uuid.uuid4()
    await bus.publish("test.event", {"x": 1}, org_id=org_id)

    assert len(received) == 1
    payload = received[0]
    assert payload["x"] == 1
    assert payload["org_id"] == org_id
    assert payload["event_type"] == "test.event"


async def test_multiple_subscribers_each_fire():
    _reset()
    calls: list[str] = []

    async def h1(envelope):
        calls.append("h1")

    async def h2(envelope):
        calls.append("h2")

    bus.subscribe("multi.event", h1)
    bus.subscribe("multi.event", h2)
    await bus.publish("multi.event", {}, org_id=uuid.uuid4())

    assert calls == ["h1", "h2"]


async def test_publish_with_no_subscribers_is_a_noop():
    """Forward-compatible — origin modules can publish events
    before consumers exist."""
    _reset()
    # No subscribers registered for this event type.
    await bus.publish("unknown.event", {"foo": "bar"}, org_id=uuid.uuid4())
    # No assertion needed beyond "doesn't raise"; the test passing
    # IS the pin.


async def test_handler_exception_is_swallowed_and_next_fires(caplog):
    _reset()
    calls: list[str] = []

    async def boom(envelope):
        raise RuntimeError("intentional")

    async def good(envelope):
        calls.append("good")

    bus.subscribe("flaky.event", boom)
    bus.subscribe("flaky.event", good)
    await bus.publish("flaky.event", {}, org_id=uuid.uuid4())

    # The second handler ran even though the first raised.
    assert calls == ["good"]


async def test_subscribe_is_idempotent_on_same_handler():
    _reset()
    calls: list[int] = []

    async def handler(envelope):
        calls.append(1)

    bus.subscribe("idem.event", handler)
    bus.subscribe("idem.event", handler)
    await bus.publish("idem.event", {}, org_id=uuid.uuid4())

    assert calls == [1]


def test_unsubscribe_removes_handler():
    _reset()
    calls: list[int] = []

    async def handler(envelope):
        calls.append(1)

    bus.subscribe("u.event", handler)
    bus.unsubscribe("u.event", handler)
    # publish runs in async; just verify the registry is empty.
    assert bus._subscribers.get("u.event") == []
