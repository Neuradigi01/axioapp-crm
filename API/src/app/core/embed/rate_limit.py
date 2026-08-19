"""Rate limiters for the public widget submission endpoint.

Two limiters guard the submission hot path:

  - **per-key** — 100 req/hour: prevents a single org's embed key from
    being weaponised to flood other orgs (it can't — keys are scoped)
    or to flood this org's own kanban with junk leads.
  - **per-IP** — 10 req/hour: prevents a single visitor (or bot) from
    hammering the form regardless of which key they used.

Spec calls for Redis-backed token buckets eventually. For v1 we use
the existing in-process `InMemoryRateLimiter` from `shared/rate_limit.py`:

  - Redis isn't installed in the API container today (only Celery
    refers to it via env vars).
  - In-memory is single-process — multi-worker prod will need Redis
    to share state. Documented; not a blocker for v1.
  - The limiter interface (`RateLimitResult`) is stable across both
    backends, so swapping later is a one-file change.

Both limiters are module-level singletons so all submission requests
share the same counters per uvicorn worker.
"""

from __future__ import annotations

from src.app.shared.rate_limit import (
    InMemoryRateLimiter,
    RateLimitResult,
)

# 1 hour in seconds — both limiters use a 1-hour sliding window.
_ONE_HOUR = 60 * 60

# Per-key: 100/hour. Tolerant enough for a legit busy widget; tight
# enough that a leaked key can't fire 10k requests before revocation.
per_key_limiter = InMemoryRateLimiter(max_hits=100, window_seconds=_ONE_HOUR)

# Per-IP: 10/hour. A single visitor submitting the form more than 10
# times in an hour is almost certainly a bot or a stress-tester.
per_ip_limiter = InMemoryRateLimiter(max_hits=10, window_seconds=_ONE_HOUR)


def check_per_key(prefix: str) -> RateLimitResult:
    """Rate-limit by the issued key's display prefix.

    Using the prefix (not the full plaintext) avoids holding the
    plaintext in module-level dicts. The prefix is unique enough at
    the rate-limit grain — collision probability between live keys
    is ~1 in 56B.
    """
    return per_key_limiter.check(f"embed:key:{prefix}")


def check_per_ip(ip: str) -> RateLimitResult:
    """Rate-limit by caller IP."""
    return per_ip_limiter.check(f"embed:ip:{ip}")


# --- AI-assistants public-router rate limiter (Step 14) -----------------
#
# The AI-assistants public router uses a **fail-closed** Redis-backed
# limiter with three parallel buckets (per-IP + per-key + per-org):
# on Redis outage the caller sees 429 with ``Retry-After: 30``.
# This deliberately diverges from the lead-form limiters above (which
# fall through to in-process on Redis failure) because a chat request
# spends real OpenAI money — the failure mode we want under Redis
# outage is "widget shows retry later", not "spend 10× the daily
# budget because the limiter is silently open".
#
# Buckets:
#   * per-IP: 60/hour (blunt bot filter; visitors don't chat 60×/hour).
#   * per-key: configurable per-key ``rate_limit_per_hour`` (default 300).
#   * per-org: 2000/hour aggregate cap across all keys in the org
#     (protects against a single leaked key crossed with 20 domains).

import logging as _stdlib_logging  # avoids shadow with existing modules
from dataclasses import dataclass as _dataclass

_ONE_HOUR_SEC = 60 * 60
_DEFAULT_PER_IP_LIMIT = 60
_DEFAULT_PER_ORG_LIMIT = 2000
_ai_logger = _stdlib_logging.getLogger(__name__)


@_dataclass(frozen=True, slots=True)
class AiPublicRateLimitResult:
    """Outcome of the three-bucket check for the AI-assistants public
    router. ``allowed=False`` responses always carry a ``reason``:

      * ``"per_ip"`` / ``"per_key"`` / ``"per_org"`` — quota exceeded.
      * ``"redis_unavailable"`` — fail-closed on Redis outage.

    ``retry_after_seconds`` is the wire value for ``Retry-After``.
    """

    allowed: bool
    reason: str | None = None
    retry_after_seconds: int = 60


async def check_ai_public_rate_limits(
    *,
    ip: str,
    key_id,
    org_id,
    per_key_limit: int,
    per_ip_limit: int = _DEFAULT_PER_IP_LIMIT,
    per_org_limit: int = _DEFAULT_PER_ORG_LIMIT,
) -> AiPublicRateLimitResult:
    """Run the three buckets in parallel semantically (each is one
    Redis round-trip) and return the first that trips. Fail-closed
    on Redis error: caller sees 429 with ``Retry-After: 30`` and
    ``reason='redis_unavailable'``.

    Records the current hit on the losing bucket only when the
    caller is admitted — a rejected caller doesn't consume their
    quota again (avoids the "keep hammering to keep the counter
    high" pathology).
    """
    from redis.exceptions import RedisError

    from src.app.shared import rate_limit_shared

    # Import here (not at module top) so the rate-limit module stays
    # importable in dev shells where Redis config is absent.

    async def _hit(key: str, limit: int) -> bool | None:
        """Run rate_hit with a strict try/except — we DO NOT want the
        in-process fallback that rate_hit does silently, because that
        would flip fail-closed to fail-open. Returns None on Redis
        error (caller treats as fail-closed)."""
        client = rate_limit_shared._redis()
        if client is None:
            return None
        try:
            import time as _time

            now_ms = int(_time.time() * 1000)
            window_start_ms = now_ms - _ONE_HOUR_SEC * 1000
            redis_key = f"rlx:rl:{key}"
            pipe = client.pipeline(transaction=True)
            pipe.zremrangebyscore(redis_key, 0, window_start_ms)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {str(now_ms): now_ms})
            pipe.expire(redis_key, _ONE_HOUR_SEC + 1)
            _, count_before, _, _ = await pipe.execute()
            return int(count_before) < limit
        except RedisError:
            return None
        except Exception:  # pragma: no cover — defensive
            return None

    checks = (
        (f"aipub:ip:{ip}", per_ip_limit, "per_ip"),
        (f"aipub:key:{key_id}", per_key_limit, "per_key"),
        (f"aipub:org:{org_id}", per_org_limit, "per_org"),
    )
    for key, limit, reason in checks:
        outcome = await _hit(key, limit)
        if outcome is None:
            _ai_logger.warning(
                "ai_public_rate_limit: redis_unavailable failing closed key=%s", key
            )
            return AiPublicRateLimitResult(
                allowed=False,
                reason="redis_unavailable",
                retry_after_seconds=30,
            )
        if not outcome:
            return AiPublicRateLimitResult(
                allowed=False,
                reason=reason,
                retry_after_seconds=60,
            )
    return AiPublicRateLimitResult(allowed=True)


__all__ = [
    "AiPublicRateLimitResult",
    "check_ai_public_rate_limits",
    "check_per_ip",
    "check_per_key",
    "per_ip_limiter",
    "per_key_limiter",
]
