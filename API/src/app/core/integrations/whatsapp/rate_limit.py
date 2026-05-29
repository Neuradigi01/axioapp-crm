"""Per-org outbound rate limiting for WhatsApp dispatch (Step 3.5.15).

In-memory token bucket — sufficient for single-process dev
(`CELERY_ENABLED=false`). Production multi-worker deployments should
swap in a Redis-backed implementation; the `TokenBucketLimiter`
interface is small enough that doing so doesn't touch callers.

Buckets are keyed by `org_id`. Refill rate is the per-org
`rate_limit_per_sec` from `whatsapp_account_configs`; burst capacity
is `2 × refill_rate` so a quiet period doesn't starve a burst-send
later. `acquire` returns immediately when a token is available;
otherwise it `asyncio.sleep`s until the next refill, then returns.

The dispatch loop calls `acquire(org_id, rate_per_sec)` once per
outbound send. Spread across multiple chunks running in parallel
(Celery workers), the bucket prevents a thundering-herd burst that
would trigger Meta's 429 rate-limit response.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class _Bucket:
    """Token-bucket state for one (key, rate) pair.

    `tokens` is the current credit, capped at `capacity`. `last` is the
    last refill timestamp. Refills happen lazily on every `acquire`
    call — no background thread needed."""

    capacity: float
    refill_rate: float            # tokens/sec
    tokens: float = field(default=0.0)
    last: float = field(default_factory=time.monotonic)


class InMemoryTokenBucketLimiter:
    """Per-key token bucket, single-process. Thread-safe via a coarse
    `Lock` (acquires happen in async code but the bucket math is
    sync-cheap — sub-microsecond — so contention is negligible)."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = Lock()

    def _get_or_create(self, key: str, *, rate: float) -> _Bucket:
        with self._lock:
            bucket = self._buckets.get(key)
            capacity = max(1.0, rate * 2.0)
            if bucket is None:
                bucket = _Bucket(
                    capacity=capacity,
                    refill_rate=rate,
                    tokens=capacity,
                )
                self._buckets[key] = bucket
            elif bucket.refill_rate != rate:
                # Operator changed the per-org rate — re-rate the
                # bucket in place. Tokens cap at the new capacity.
                bucket.refill_rate = rate
                bucket.capacity = capacity
                bucket.tokens = min(bucket.tokens, capacity)
            return bucket

    def _refill(self, bucket: _Bucket, *, now: float) -> None:
        elapsed = now - bucket.last
        if elapsed <= 0:
            return
        bucket.tokens = min(
            bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate
        )
        bucket.last = now

    async def acquire(
        self, key: str, *, rate_per_sec: float, count: float = 1.0
    ) -> float:
        """Block until `count` tokens are available; return the total
        seconds spent waiting (0 when no wait was needed).

        Implementation: lazy-refill the bucket on every call; if
        `tokens < count`, compute the wait time deterministically
        from the refill rate, `await asyncio.sleep`, then drain.

        Single-process semantics — for multi-worker, swap in a Redis
        implementation that holds the bucket state centrally."""
        if rate_per_sec <= 0:
            # Defensive: a zero rate would lock the queue forever.
            # Treat as "unlimited" so a misconfigured row doesn't
            # silently freeze dispatch.
            return 0.0
        if count <= 0:
            return 0.0

        bucket = self._get_or_create(key, rate=rate_per_sec)
        waited = 0.0

        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(bucket, now=now)
                if bucket.tokens >= count:
                    bucket.tokens -= count
                    return waited
                shortfall = count - bucket.tokens
                wait_for = shortfall / bucket.refill_rate
            # Release the lock before sleeping so other coroutines can
            # advance their own buckets.
            await asyncio.sleep(wait_for)
            waited += wait_for

    def reset(self, key: str | None = None) -> None:
        """Test helper — drop the bucket(s)."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


_wa_limiter = InMemoryTokenBucketLimiter()


def get_wa_rate_limiter() -> InMemoryTokenBucketLimiter:
    """Module-level limiter the dispatch path uses. Singleton so all
    concurrent sends share the same per-org bucket state within the
    process."""
    return _wa_limiter


async def acquire_wa_rate_token(
    org_id: uuid.UUID, *, rate_per_sec: int, count: int = 1
) -> float:
    """Convenience wrapper — `acquire(str(org_id), ...)` with int
    rate/count. Returns waited-seconds."""
    return await _wa_limiter.acquire(
        str(org_id), rate_per_sec=float(rate_per_sec), count=float(count)
    )


__all__ = [
    "InMemoryTokenBucketLimiter",
    "acquire_wa_rate_token",
    "get_wa_rate_limiter",
]
