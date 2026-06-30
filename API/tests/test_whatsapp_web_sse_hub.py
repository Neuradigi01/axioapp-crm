"""Step 6 — SSE hub pub/sub tests (asyncio-only, no FastAPI)."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from src.app.core.integrations.whatsapp_web.sse_hub import SSEHub


async def _wait_for_subscribers(hub: SSEHub, key: uuid.UUID, n: int) -> None:
    """Spin until the hub reports ``n`` subscribers for ``key``. The
    subscribe coroutine only registers after its first ``__anext__()``
    call awakens it, so tests start a task and wait for the side-effect."""
    for _ in range(100):
        if hub.subscriber_count(key) >= n:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"expected {n} subscribers on {key}, got {hub.subscriber_count(key)}"
    )


@pytest.mark.asyncio
async def test_publish_subscribe_round_trip() -> None:
    hub = SSEHub()
    integration_id = uuid.uuid4()
    sub = hub.subscribe(integration_id)
    fetch = asyncio.create_task(sub.__anext__())
    await _wait_for_subscribers(hub, integration_id, 1)

    sent = hub.publish(integration_id, {"type": "qr_updated", "qr_data_url": "data:..."})
    assert sent == 1

    received = await asyncio.wait_for(fetch, timeout=1.0)
    assert received == {"type": "qr_updated", "qr_data_url": "data:..."}
    await sub.aclose()


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_the_payload() -> None:
    hub = SSEHub()
    integration_id = uuid.uuid4()

    sub_a = hub.subscribe(integration_id)
    sub_b = hub.subscribe(integration_id)
    fetch_a = asyncio.create_task(sub_a.__anext__())
    fetch_b = asyncio.create_task(sub_b.__anext__())
    await _wait_for_subscribers(hub, integration_id, 2)

    sent = hub.publish(integration_id, {"type": "connected"})
    assert sent == 2

    a = await asyncio.wait_for(fetch_a, timeout=1.0)
    b = await asyncio.wait_for(fetch_b, timeout=1.0)
    assert a == {"type": "connected"}
    assert b == {"type": "connected"}
    await sub_a.aclose()
    await sub_b.aclose()


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_fanout() -> None:
    hub = SSEHub()
    integration_id = uuid.uuid4()

    sub = hub.subscribe(integration_id)
    fetch = asyncio.create_task(sub.__anext__())
    await _wait_for_subscribers(hub, integration_id, 1)

    # Cancel the pending get + close the generator.
    fetch.cancel()
    try:
        await fetch
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    await sub.aclose()
    await asyncio.sleep(0.01)

    assert hub.subscriber_count(integration_id) == 0
    sent = hub.publish(integration_id, {"type": "qr_updated"})
    assert sent == 0


@pytest.mark.asyncio
async def test_publish_to_unsubscribed_key_is_noop() -> None:
    hub = SSEHub()
    delivered = hub.publish(uuid.uuid4(), {"type": "qr_updated"})
    assert delivered == 0


@pytest.mark.asyncio
async def test_slow_consumer_does_not_block_publisher() -> None:
    # Hub uses bounded queues (size 32) and drops the oldest unread
    # frame on overflow. Confirm: 50 publishes against a registered-
    # but-never-read subscriber complete synchronously.
    hub = SSEHub()
    integration_id = uuid.uuid4()
    sub = hub.subscribe(integration_id)
    fetch = asyncio.create_task(sub.__anext__())
    await _wait_for_subscribers(hub, integration_id, 1)

    for i in range(50):
        delivered = hub.publish(integration_id, {"i": i})
        assert delivered == 1

    fetch.cancel()
    try:
        await fetch
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    await sub.aclose()
