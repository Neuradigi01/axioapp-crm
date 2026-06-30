"""In-memory pub/sub for the WhatsApp Web SSE stream.

Single-replica only. Multi-replica needs Redis pub/sub (deferred,
mirrors the sidecar's own single-replica constraint). The hub stays
fully in-process so the SPA's EventSource gets sub-second latency
on QR / status updates without polling.

Keys are ``integration_id`` (UUID): one fan-out queue per subscriber.
Subscribers register through ``subscribe()`` (async generator) and
the SSE endpoint streams everything yielded. ``publish()`` is fire-
and-forget — payloads are put on every queue; slow consumers don't
block the publisher because ``Queue.put_nowait`` is used inside a
bounded queue that drops the oldest unread frame on overflow.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

# Bound per subscriber — large enough to absorb a QR + status burst
# during pairing, small enough to bound memory if a stuck client
# never reads.
_QUEUE_MAX = 32


class SSEHub:
    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def _register(
        self, integration_id: uuid.UUID
    ) -> asyncio.Queue[dict[str, Any]]:
        async with self._lock:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
            self._subscribers.setdefault(integration_id, []).append(queue)
            return queue

    async def _unregister(
        self,
        integration_id: uuid.UUID,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        async with self._lock:
            queues = self._subscribers.get(integration_id)
            if not queues:
                return
            try:
                queues.remove(queue)
            except ValueError:
                pass
            if not queues:
                self._subscribers.pop(integration_id, None)

    def publish(
        self, integration_id: uuid.UUID, payload: dict[str, Any]
    ) -> int:
        """Fan-out one payload to every subscriber of an integration.

        Returns the number of subscribers the payload reached. Drops
        the oldest unread frame when a subscriber's queue is full
        (slow consumer must not back-pressure the producer).
        """
        queues = self._subscribers.get(integration_id, ())
        delivered = 0
        for queue in list(queues):
            while True:
                try:
                    queue.put_nowait(payload)
                    delivered += 1
                    break
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover
                        break
        return delivered

    async def subscribe(
        self, integration_id: uuid.UUID
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every payload published for ``integration_id``.

        The generator runs until the caller stops iterating (client
        disconnect). The SSE endpoint wraps this in a heartbeat so a
        long-idle pairing window doesn't drop the connection.
        """
        queue = await self._register(integration_id)
        try:
            while True:
                payload = await queue.get()
                yield payload
        finally:
            await self._unregister(integration_id, queue)

    def subscriber_count(self, integration_id: uuid.UUID) -> int:
        return len(self._subscribers.get(integration_id, ()))


hub: SSEHub = SSEHub()


__all__ = ["SSEHub", "hub"]
