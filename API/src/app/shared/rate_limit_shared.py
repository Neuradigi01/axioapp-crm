"""Cross-worker cooldown + sliding-window helpers.

Two primitives used by multiple modules — keyword-rule cooldown
(K.41) and public quick-link redirect throttling (K.68) — both used
to live as in-process token buckets. That was correct for the single-
worker default but silently regressed under horizontal scale: each
Celery / uvicorn worker had its own bucket, so the effective limit
was *N × configured limit* and a contact could receive N duplicate
auto-replies within the same "cooldown" window.

This module wraps both primitives with a Redis-first backend that
gracefully falls back to the in-process store when Redis is
unreachable (dev shells without Redis running, transient network
blips). Behaviour matches the prior in-process implementation on the
fallback path — nothing else changes for existing callers.

Design notes:

- **Best-effort semantics**: Redis errors log at WARNING once per
  process and fall through to in-process. We never fail a webhook
  or public-page fetch because Redis burped.
- **TTL-based invalidation**: cooldown = SET NX PX (atomic
  "set-if-not-exists with expiry"); rate limit = ZADD + ZREMRANGE
  over a sliding window sorted-set. Both self-clean without a
  sweeper task.
- **Keyspace prefix**: ``rlx:`` for all keys here so operators can
  ``KEYS rlx:*`` / ``DEL rlx:...`` without touching Celery's broker
  keys in the same DB.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from redis import asyncio as aioredis

from config import REDIS_DB_BROKER, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger(__name__)

_KEY_PREFIX = "rlx:"

# --- Redis client (lazy, shared) ------------------------------------------

_redis_client: aioredis.Redis | None = None
_redis_disabled = False
_redis_disabled_logged = False
_client_lock = threading.Lock()


def _redis() -> aioredis.Redis | None:
    """Return a shared aioredis client, or ``None`` if construction
    fails (Redis config missing / library import broken). Once
    ``_redis_disabled`` flips to True we don't retry — the process
    stays on the in-process fallback until restarted.
    """
    global _redis_client, _redis_disabled, _redis_disabled_logged
    if _redis_disabled:
        return None
    if _redis_client is not None:
        return _redis_client
    with _client_lock:
        # Re-check inside the lock — another thread may have built it.
        if _redis_client is not None:
            return _redis_client
        try:
            _redis_client = aioredis.Redis(
                host=REDIS_HOST,
                port=int(REDIS_PORT),
                db=REDIS_DB_BROKER,
                password=REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
        except Exception:  # pragma: no cover — defensive
            _redis_disabled = True
            if not _redis_disabled_logged:
                logger.exception(
                    "rate_limit_shared: Redis client construction failed; "
                    "using in-process fallback for cooldown/rate-limit"
                )
                _redis_disabled_logged = True
            return None
    return _redis_client


def _log_fallback_once(reason: str) -> None:
    global _redis_disabled_logged
    if not _redis_disabled_logged:
        logger.warning(
            "rate_limit_shared: falling back to in-process store (%s)", reason
        )
        _redis_disabled_logged = True


# --- Cooldown (K.41 keyword-rule) -----------------------------------------
#
# One-shot lock: return True if the caller "won" the cooldown (i.e.
# the rule is not currently on cooldown for this contact; the lock is
# now held for ``ttl_seconds``). Return False if someone else already
# holds it.

_INPROC_COOLDOWN: dict[str, float] = {}
_INPROC_COOLDOWN_LOCK = threading.Lock()


async def acquire_cooldown(key: str, ttl_seconds: int) -> bool:
    """Try to claim a cooldown slot for ``key``.

    Returns True on the first call within the window (caller may
    proceed), False on subsequent calls (caller is on cooldown).
    Both worker-shared (Redis) and single-worker (in-process) paths
    have identical semantics.
    """
    redis_key = f"{_KEY_PREFIX}cd:{key}"
    client = _redis()
    if client is not None:
        try:
            # SET NX PX = atomic "set if not exists with TTL in ms".
            result = await client.set(redis_key, "1", nx=True, px=ttl_seconds * 1000)
            return bool(result)
        except Exception as exc:  # pragma: no cover — defensive
            _log_fallback_once(f"cooldown redis error: {exc}")
            # Fall through to in-process below.

    now = time.monotonic()
    with _INPROC_COOLDOWN_LOCK:
        expiry = _INPROC_COOLDOWN.get(key)
        if expiry is not None and expiry > now:
            return False
        _INPROC_COOLDOWN[key] = now + ttl_seconds
        return True


async def is_on_cooldown(key: str) -> bool:
    """Read-only check without claiming the slot. Useful for
    tests / diagnostics. Callers that need atomicity should use
    :func:`acquire_cooldown` instead."""
    redis_key = f"{_KEY_PREFIX}cd:{key}"
    client = _redis()
    if client is not None:
        try:
            existing = await client.get(redis_key)
            return existing is not None
        except Exception:  # pragma: no cover — defensive
            pass

    now = time.monotonic()
    with _INPROC_COOLDOWN_LOCK:
        expiry = _INPROC_COOLDOWN.get(key)
        return expiry is not None and expiry > now


# --- Sliding-window rate limit (K.68 quick-link redirect) -----------------
#
# ``rate_hit`` returns True when the caller is UNDER the limit and
# should be allowed through; False when they're OVER and should be
# blocked (429 / etc.).

_INPROC_WINDOWS: dict[str, Deque[float]] = defaultdict(deque)
_INPROC_WINDOW_LOCK = threading.Lock()


async def rate_hit(key: str, limit: int, window_seconds: int) -> bool:
    """Sliding-window admission check.

    Returns True if the caller has fewer than ``limit`` events in the
    last ``window_seconds`` (and records the current event); False
    otherwise.

    Redis backend uses ZADD + ZREMRANGEBYSCORE + ZCARD in a MULTI
    transaction so concurrent hits from the same key can't both slip
    through under a race. In-process fallback uses a per-key deque
    and the module-level lock.
    """
    redis_key = f"{_KEY_PREFIX}rl:{key}"
    client = _redis()
    if client is not None:
        try:
            now_ms = int(time.time() * 1000)
            window_start_ms = now_ms - window_seconds * 1000
            pipe = client.pipeline(transaction=True)
            pipe.zremrangebyscore(redis_key, 0, window_start_ms)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {str(now_ms): now_ms})
            pipe.expire(redis_key, window_seconds + 1)
            _, count_before, _, _ = await pipe.execute()
            # count_before is the size AFTER purging old entries but
            # BEFORE we added our own — so we're admitted iff it was
            # strictly less than the limit.
            return int(count_before) < limit
        except Exception as exc:  # pragma: no cover — defensive
            _log_fallback_once(f"rate limit redis error: {exc}")

    now = time.monotonic()
    window_start = now - window_seconds
    with _INPROC_WINDOW_LOCK:
        window = _INPROC_WINDOWS[key]
        while window and window[0] < window_start:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


__all__ = ["acquire_cooldown", "is_on_cooldown", "rate_hit"]
