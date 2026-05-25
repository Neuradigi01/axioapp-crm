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
per_key_limiter = InMemoryRateLimiter(
    max_hits=100, window_seconds=_ONE_HOUR
)

# Per-IP: 10/hour. A single visitor submitting the form more than 10
# times in an hour is almost certainly a bot or a stress-tester.
per_ip_limiter = InMemoryRateLimiter(
    max_hits=10, window_seconds=_ONE_HOUR
)


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


__all__ = ["check_per_ip", "check_per_key", "per_ip_limiter", "per_key_limiter"]
