"""In-memory registry of in-flight SSE streams
(``tasks/ai-assistants`` Step 14).

Each active public-widget stream registers a cancel token keyed by
``(embed_key_id, session_token)`` when it starts and deregisters
when it finishes. The operator's revoke-now endpoint walks the
registry + flips every matching stream's cancel flag so the runtime
tears down its OpenAI stream on the next chunk boundary.

Single-process only in v1 — a multi-worker uvicorn deployment
needs a Redis pub/sub bridge to reach streams on other workers.
Documented; Step 17's janitor is where a future upgrade would land.

Thread-safety: the registry lives entirely inside asyncio's
event-loop thread, so a plain ``dict`` + reads/writes are safe
without an explicit lock. If we ever cross a thread boundary
(background sync worker), swap to :class:`threading.RLock`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _StreamHandle:
    """One in-flight stream. ``cancelled`` is the only mutable field —
    the runtime polls it every N chunks (same disconnect-check
    cadence as :func:`~core.ai_assistants.runtime.ChatRuntime.stream_reply`).
    """

    embed_key_id: uuid.UUID
    session_token: str
    cancelled: bool = field(default=False)


class SseStreamRegistry:
    """Process-global registry. Instantiated once at module scope
    (``registry`` below) — callers use the module functions to keep
    the surface small."""

    def __init__(self) -> None:
        self._handles: dict[str, _StreamHandle] = {}

    @staticmethod
    def _make_id(embed_key_id: uuid.UUID, session_token: str) -> str:
        # Use ``session_token`` as the intra-key discriminator so two
        # concurrent tabs with the same key each get their own handle.
        return f"{embed_key_id}:{session_token}"

    def register(
        self,
        *,
        embed_key_id: uuid.UUID,
        session_token: str,
    ) -> _StreamHandle:
        handle = _StreamHandle(
            embed_key_id=embed_key_id,
            session_token=session_token,
        )
        self._handles[self._make_id(embed_key_id, session_token)] = handle
        return handle

    def deregister(
        self,
        *,
        embed_key_id: uuid.UUID,
        session_token: str,
    ) -> None:
        self._handles.pop(self._make_id(embed_key_id, session_token), None)

    def cancel_by_embed_key(self, embed_key_id: uuid.UUID) -> int:
        """Flip ``cancelled=True`` on every handle whose key matches.
        Returns the count of handles cancelled. The runtime observes
        the flag on its next disconnect-check tick + exits its
        stream loop cleanly."""
        count = 0
        for handle in list(self._handles.values()):
            if handle.embed_key_id == embed_key_id and not handle.cancelled:
                handle.cancelled = True
                count += 1
        if count:
            logger.info(
                "sse_registry.cancel_by_embed_key key=%s cancelled=%d",
                embed_key_id,
                count,
            )
        return count

    def is_cancelled(
        self,
        *,
        embed_key_id: uuid.UUID,
        session_token: str,
    ) -> bool:
        handle = self._handles.get(self._make_id(embed_key_id, session_token))
        return handle is not None and handle.cancelled

    def active_count(self) -> int:
        """For diagnostics + tests."""
        return len(self._handles)


# Module-global singleton. Deliberate — the registry has no state
# worth injecting for tests (tests can reach in via ``registry._handles``
# or call the public methods on this instance).
registry = SseStreamRegistry()


__all__ = ["SseStreamRegistry", "registry"]
