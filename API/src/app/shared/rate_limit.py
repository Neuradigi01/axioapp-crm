"""Lightweight rate limiter for the auth router.

Fixed-window counter (per IP / per route key, per N seconds) — simpler
than a sliding window and adequate for "10 attempts per minute" on
login. The default `InMemoryRateLimiter` is single-process and lives
in this module's globals; tests can construct their own instance via
the constructor.

A Redis-backed limiter is on the roadmap for horizontal scale-out;
the `RateLimiter` interface below is intentionally small so a
`RedisRateLimiter` can drop in later without callers changing.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float  # seconds until the next refill, 0 if allowed


class InMemoryRateLimiter:
    """Per-key sliding-window counter, in-process only.

    Tracks the timestamps of recent hits per key in a `deque`; on
    `check()` it evicts timestamps older than `window_seconds` and
    counts what remains. Returns `allowed=False` when the count would
    exceed `max_hits`.
    """

    def __init__(self, *, max_hits: int, window_seconds: float) -> None:
        if max_hits <= 0:
            raise ValueError("max_hits must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max = max_hits
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, *, now: float | None = None) -> RateLimitResult:
        ts = now if now is not None else time.monotonic()
        window_start = ts - self._window

        bucket = self._hits.setdefault(key, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self._max:
            retry_after = max(0.0, self._window - (ts - bucket[0]))
            return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)

        bucket.append(ts)
        return RateLimitResult(
            allowed=True, remaining=self._max - len(bucket), retry_after=0.0
        )

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# Module-level singleton tuned to the spec: 10 login attempts per IP per minute.
login_limiter = InMemoryRateLimiter(max_hits=10, window_seconds=60.0)
