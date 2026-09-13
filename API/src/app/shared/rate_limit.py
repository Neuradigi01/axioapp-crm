"""Rate limiters — in-process (auth) + Redis-backed sliding window
(public-ingest, embed, ai-assistants).

The in-memory ``InMemoryRateLimiter`` + module singleton ``login_limiter``
below back the auth-router's "10 attempts per IP per minute" guard.
Single-process is correct there — auth traffic is dwarfed by product
traffic and a per-worker bucket is not exploitable.

The Redis-backed ``check_shared_sliding_window`` below is what every
public-facing surface (embed submissions, custom-event ingest, AI
widget) reaches for. It sits on top of the shared aioredis client from
``rate_limit_shared`` and uses a Lua script for the
``ZREMRANGEBYSCORE → ZCARD → ZADD`` triple so concurrent hits on the
same bucket can't both slip through a race. Callers pick a
``fail_mode`` explicitly — ``"open"`` for the widget lead form
(behavioural continuity with the in-process legacy limiter), ``"closed"``
for anything that spends money on a hit (AI) or that must reject
replays under Redis outage (events ingest).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Literal


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
        return RateLimitResult(allowed=True, remaining=self._max - len(bucket), retry_after=0.0)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# Module-level singleton tuned to the spec: 10 login attempts per IP per minute.
login_limiter = InMemoryRateLimiter(max_hits=10, window_seconds=60.0)


# --- Redis-backed sliding window (public-ingest, embed, AI widget) --------
#
# Sits on top of the aioredis client shared with ``rate_limit_shared``
# (K.41 keyword-cooldown + K.68 quick-link limiter). Uses a Lua script
# so ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE runs as one server-side
# operation; two concurrent hits from the same bucket key can't both
# land under the limit through a MULTI-EXEC race.


_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SharedRateLimitResult:
    """Outcome of a Redis-backed sliding-window check.

    ``reason`` is always set on rejection so the caller can surface it
    to logs / audit (``"limit_exceeded"``, ``"redis_unavailable"``, or
    a caller-provided bucket label). ``retry_after_seconds`` is the
    wire value for the ``Retry-After`` header.
    """

    allowed: bool
    remaining: int
    retry_after_seconds: int
    reason: str | None = None


# ZREMRANGEBYSCORE + ZCARD + ZADD + EXPIRE, atomic. ARGV[1]=now_ms,
# ARGV[2]=window_ms, ARGV[3]=limit, ARGV[4]=unique-member (so two hits
# in the same ms don't collapse into one ZADD entry). KEYS[1]=bucket
# key.
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = 0
  if oldest[2] then
    retry_ms = (tonumber(oldest[2]) + window) - now
    if retry_ms < 0 then retry_ms = 0 end
  end
  return {0, 0, retry_ms}
end
redis.call('ZADD', KEYS[1], now, member)
redis.call('PEXPIRE', KEYS[1], window + 1000)
return {1, limit - count - 1, 0}
"""

_SCRIPT_SHA: str | None = None


async def _load_script(client) -> str | None:
    """Return the SCRIPT LOAD sha of the sliding-window Lua, caching
    it for subsequent calls. Redis persists loaded scripts until
    FLUSHALL so the SHA stays valid across worker restarts, and a
    NOSCRIPT reply from EVALSHA transparently falls back to EVAL."""
    global _SCRIPT_SHA
    if _SCRIPT_SHA is not None:
        return _SCRIPT_SHA
    try:
        _SCRIPT_SHA = await client.script_load(_SLIDING_WINDOW_LUA)
    except Exception:  # pragma: no cover — defensive
        return None
    return _SCRIPT_SHA


async def check_shared_sliding_window(
    *,
    bucket_key: str,
    limit: int,
    window_seconds: int,
    fail_mode: Literal["open", "closed"] = "closed",
    fail_closed_retry_after: int = 30,
) -> SharedRateLimitResult:
    """Sliding-window admission check against Redis.

    Returns ``allowed=True`` when the caller is under the limit AND
    the current hit was recorded. On Redis outage:

      * ``fail_mode="open"``  — return allowed=True with reason=
        ``"redis_unavailable"``. Caller still sees the header but the
        request is admitted (widget lead-form legacy behaviour).
      * ``fail_mode="closed"`` — return allowed=False,
        retry_after=``fail_closed_retry_after``, reason=
        ``"redis_unavailable"``. Caller responds 429/503.

    ``bucket_key`` is the caller-composed sort-set key. Convention:

        pi:rl:{scope}:{org_id}:{bucket_type}:{value}
        pi:rl:{scope}:pre-auth:{bucket_type}:{value}

    where ``scope`` is one of ``embed``, ``events``, ``aipub``.
    """
    from src.app.shared import rate_limit_shared  # local — dev shells

    client = rate_limit_shared._redis()
    if client is None:
        return _fail_result(fail_mode, fail_closed_retry_after)

    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000
    member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
    sha = await _load_script(client)
    try:
        if sha is not None:
            try:
                result = await client.evalsha(
                    sha, 1, bucket_key, now_ms, window_ms, limit, member
                )
            except Exception as exc:
                if "NOSCRIPT" in str(exc):
                    result = await client.eval(
                        _SLIDING_WINDOW_LUA, 1, bucket_key, now_ms, window_ms, limit, member
                    )
                else:
                    raise
        else:
            result = await client.eval(
                _SLIDING_WINDOW_LUA, 1, bucket_key, now_ms, window_ms, limit, member
            )
    except Exception as exc:  # pragma: no cover — Redis outage path
        _logger.warning(
            "check_shared_sliding_window: redis error %s (bucket=%s, fail_mode=%s)",
            exc,
            bucket_key,
            fail_mode,
        )
        return _fail_result(fail_mode, fail_closed_retry_after)

    allowed = bool(int(result[0]))
    remaining = int(result[1])
    retry_ms = int(result[2])
    if allowed:
        return SharedRateLimitResult(
            allowed=True, remaining=remaining, retry_after_seconds=0
        )
    return SharedRateLimitResult(
        allowed=False,
        remaining=0,
        retry_after_seconds=max(1, (retry_ms + 999) // 1000),
        reason="limit_exceeded",
    )


def _fail_result(
    fail_mode: Literal["open", "closed"], fail_closed_retry_after: int
) -> SharedRateLimitResult:
    if fail_mode == "open":
        return SharedRateLimitResult(
            allowed=True,
            remaining=-1,
            retry_after_seconds=0,
            reason="redis_unavailable",
        )
    return SharedRateLimitResult(
        allowed=False,
        remaining=0,
        retry_after_seconds=fail_closed_retry_after,
        reason="redis_unavailable",
    )


def _reset_lua_cache_for_tests() -> None:
    """Test hook — flushes the module-level SHA cache so a test that
    monkeypatches the Redis client sees a fresh SCRIPT LOAD."""
    global _SCRIPT_SHA
    _SCRIPT_SHA = None


def compose_bucket_key(
    *,
    scope: str,
    bucket_type: str,
    value: str,
    org_id: uuid.UUID | None = None,
) -> str:
    """Build a canonical bucket key.

    ``scope`` — surface identifier (``embed``, ``events``, ``aipub``).
    ``bucket_type`` — ``ip`` / ``key`` / ``ident`` / ``org``.
    ``value`` — the actual value being throttled (hashed IP, key id,
    identifier hash, org id).
    ``org_id`` — set for post-auth buckets, omitted for pre-auth (where
    org isn't known yet).
    """
    if org_id is not None:
        return f"pi:rl:{scope}:org:{org_id}:{bucket_type}:{value}"
    return f"pi:rl:{scope}:pre-auth:{bucket_type}:{value}"


__all__ = [
    "InMemoryRateLimiter",
    "RateLimitResult",
    "SharedRateLimitResult",
    "check_shared_sliding_window",
    "compose_bucket_key",
    "login_limiter",
]
