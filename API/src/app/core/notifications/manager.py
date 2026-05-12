"""In-process WebSocket connection manager keyed by user_id.

This is single-process by design (Phase 2). Multi-worker scaling via
Redis pub/sub is deferred to Phase 6 — when we add it, the public
surface here (`connect` / `disconnect` / `broadcast`) stays the same;
only the internals fan out across processes.

A user may have multiple concurrent connections (laptop + phone + a
second tab); we store a `set` per user_id and `broadcast` iterates all
sockets, removing any that fail to send (treats them as dropped). All
mutations of the registry happen under a single `asyncio.Lock` so two
concurrent connects don't race.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Singleton — instantiated once at module load (`manager` below)."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(ws)
        logger.debug(
            "notifications.ws connected user_id=%s total=%d", user_id, self.size_for(user_id)
        )

    async def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if sockets is not None:
                sockets.discard(ws)
                if not sockets:
                    self._connections.pop(user_id, None)
        logger.debug(
            "notifications.ws disconnected user_id=%s remaining=%d",
            user_id,
            self.size_for(user_id),
        )

    async def broadcast(self, user_id: uuid.UUID, payload: dict[str, Any]) -> int:
        """Send `payload` to every connection registered for `user_id`.

        Returns the number of sockets the message reached. Sockets that
        raise on send are dropped from the registry (treated as dead).
        """
        async with self._lock:
            sockets = list(self._connections.get(user_id, ()))
        if not sockets:
            return 0

        # Serialise once; everyone gets the same bytes.
        text = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        sent = 0
        for ws in sockets:
            try:
                await ws.send_text(text)
                sent += 1
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                bucket = self._connections.get(user_id)
                if bucket is not None:
                    for ws in dead:
                        bucket.discard(ws)
                    if not bucket:
                        self._connections.pop(user_id, None)
        return sent

    def size_for(self, user_id: uuid.UUID) -> int:
        return len(self._connections.get(user_id, set()))

    def is_connected(self, user_id: uuid.UUID) -> bool:
        return user_id in self._connections


manager = ConnectionManager()
