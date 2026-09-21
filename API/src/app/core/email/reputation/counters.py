"""Redis time-bucketed counters for 24h rolling reputation events.

Track 4 stores rolling event counts in Redis rather than in
Postgres (would balloon rows on every delivery) or as a single
integer per (org, envelope) (loses "when did this counter last go
up" for the rolling window).

Design:

  * **Key format:** ``rep:{org_id}:{envelope}:{domain_or_'none'}:{event}:{bucket_hour}``
    where ``bucket_hour = int(time.time() / 3600)``. One key per hour
    bucket so a 24h read is 24 GETs (or a single MGET pipeline).

  * **Write:** :func:`incr_counter` INCRs the current-hour bucket + sets
    a 25h TTL (24h window + 1h grace so the sweep sees the last bucket
    before Redis expires it). Atomic + idempotent-friendly.

  * **Read:** :func:`sum_last_24h` MGETs the last 24 hour-bucket keys
    in one pipeline round-trip and sums. Missing buckets (never
    written) count as 0 — no per-bucket exists-check.

  * **Sweep:** :func:`trim_older_than_24h_all_orgs` is a defensive
    hourly Celery beat. Redis' TTL already expires the buckets;
    this catch-net exists for a hypothetical rogue write with a
    missing TTL (crash-mid-INCR). Uses ``SCAN`` (not ``KEYS``) so
    a large keyspace doesn't block the Redis server.

Fail-soft: every function catches Redis errors and returns a
zero-valued default. The send-gate must never wedge on a Redis blip
— the worst that can happen from a Redis outage is we send a bit
more than the cap for the outage duration. Alternative (fail-closed
on the gate) would drop revenue during a partial outage; the manager
picked availability over strict cap enforcement here.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Literal

from redis import asyncio as aioredis
from redis.exceptions import RedisError

from config import REDIS_DB_BROKER, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger(__name__)


# All rep-counter keys carry this prefix so ``KEYS rep:*`` / ``DEL
# rep:...`` doesn't touch the rate-limit helpers' ``rlx:`` keyspace or
# Celery's broker keys in the same DB.
_KEY_PREFIX = "rep"

# 24-hour rolling window + 1h grace so the trim sweep sees the last
# bucket before TTL wipes it. Kept slightly above 24h so a manual
# ``sum_last_24h`` at the top of the hour doesn't lose a bucket that's
# about to expire.
_BUCKET_TTL_SECONDS = 25 * 3600

# The four events Track 4 counts. Explicit Literal so callers can't
# typo "compalined" and silently write to a dead key. Add new event
# types here + at the events-webhook (Step 3).
EventKind = Literal["delivered", "bounced", "complained", "unsubscribed"]

# Number of hour buckets summed per ``sum_last_24h`` call. Kept as a
# module constant so tests can pin the exact pipeline depth without
# hard-coding the number twice.
BUCKETS_PER_WINDOW = 24


# --- Redis client (lazy, shared) ------------------------------------------
#
# Mirrors ``rate_limit_shared._redis`` — one lazily-constructed
# ``aioredis.Redis`` per process, disabled permanently on the first
# construction failure so we don't spam the log every send.

_redis_client: aioredis.Redis | None = None
_redis_disabled = False


def _redis() -> aioredis.Redis | None:
    global _redis_client, _redis_disabled
    if _redis_disabled:
        return None
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
        logger.exception(
            "reputation.counters: Redis client construction failed; "
            "counters disabled for this process"
        )
        return None
    return _redis_client


# --- Key construction ------------------------------------------------------


def _current_bucket() -> int:
    """Current hour bucket. ``int(time.time() / 3600)`` — same value
    every call within a wall-clock hour."""
    return int(time.time() / 3600)


def _bucket_key(
    *,
    org_id: uuid.UUID | str,
    envelope: str,
    domain_id: uuid.UUID | str | None,
    event: EventKind,
    bucket: int,
) -> str:
    """Compose one bucket key. ``domain_id`` collapses to the literal
    ``'none'`` for ``platform_from`` — using the empty string would
    look identical to a bug that dropped the id."""
    domain_segment = str(domain_id) if domain_id is not None else "none"
    return f"{_KEY_PREFIX}:{org_id}:{envelope}:{domain_segment}:{event}:{bucket}"


# --- Public API ------------------------------------------------------------


async def incr_counter(
    *,
    org_id: uuid.UUID,
    envelope: str,
    domain_id: uuid.UUID | None,
    event: EventKind,
    amount: int = 1,
) -> None:
    """Atomically increment the current-hour bucket for one event
    kind. Sets the 25h TTL every write (Redis lets a repeat EXPIRE
    push the deadline forward — deliberately, so hot keys don't
    expire mid-window even if the very first write raced with the
    EXPIRE).

    Fail-soft: a Redis outage returns silently. The send-gate reads
    ``sum_last_24h`` on the next dispatch — a lost INCR under a Redis
    blip just means the gate sees a slightly stale count; nothing
    breaks.
    """
    client = _redis()
    if client is None:
        return
    key = _bucket_key(
        org_id=org_id,
        envelope=envelope,
        domain_id=domain_id,
        event=event,
        bucket=_current_bucket(),
    )
    try:
        pipe = client.pipeline()
        pipe.incrby(key, amount)
        pipe.expire(key, _BUCKET_TTL_SECONDS)
        await pipe.execute()
    except RedisError:
        logger.warning(
            "reputation.counters.incr_counter: Redis write failed "
            "org=%s envelope=%s event=%s (counter drift %+d)",
            org_id,
            envelope,
            event,
            amount,
        )


async def sum_last_24h(
    *,
    org_id: uuid.UUID,
    envelope: str,
    domain_id: uuid.UUID | None,
    event: EventKind,
) -> int:
    """Sum the last :data:`BUCKETS_PER_WINDOW` hour buckets for one
    event kind. Single pipelined MGET — one round-trip regardless of
    how many buckets are populated.

    Fail-soft: Redis outage returns 0. Caller (the evaluator) should
    treat a 0 result as "no evidence yet" (event floor check catches
    this before ratios fire).
    """
    client = _redis()
    if client is None:
        return 0
    now_bucket = _current_bucket()
    keys = [
        _bucket_key(
            org_id=org_id,
            envelope=envelope,
            domain_id=domain_id,
            event=event,
            bucket=now_bucket - offset,
        )
        for offset in range(BUCKETS_PER_WINDOW)
    ]
    try:
        values = await client.mget(keys)
    except RedisError:
        logger.warning(
            "reputation.counters.sum_last_24h: Redis read failed org=%s envelope=%s event=%s",
            org_id,
            envelope,
            event,
        )
        return 0
    total = 0
    for raw in values:
        if raw is None:
            continue
        try:
            total += int(raw)
        except (TypeError, ValueError):
            # A non-integer value in a counter key means either a bug
            # elsewhere or a manual DEL/SET. Log + skip rather than
            # crash the eval.
            logger.warning(
                "reputation.counters.sum_last_24h: non-integer bucket "
                "value ignored org=%s envelope=%s event=%s",
                org_id,
                envelope,
                event,
            )
    return total


async def trim_older_than_24h_all_orgs() -> int:
    """Defensive Redis sweep. Redis' TTL already expires stale
    buckets; this catch-net exists for a hypothetical rogue write
    with a missing TTL (crash-mid-INCR before EXPIRE, though the
    pipeline in :func:`incr_counter` sends both atomically).

    Scans (not ``KEYS``) the ``rep:*`` keyspace, decodes the bucket
    suffix, and DELs anything older than
    :data:`BUCKETS_PER_WINDOW` buckets. Returns the count deleted.

    Called by an hourly Celery beat (Step 4 wires it) so a leaked
    key can't accumulate forever.
    """
    client = _redis()
    if client is None:
        return 0
    now_bucket = _current_bucket()
    cutoff_bucket = now_bucket - BUCKETS_PER_WINDOW
    deleted = 0
    try:
        async for raw_key in client.scan_iter(match=f"{_KEY_PREFIX}:*", count=500):
            # Key shape: rep:<org>:<envelope>:<domain>:<event>:<bucket>
            parts = raw_key.split(":")
            if len(parts) != 6:
                continue
            try:
                bucket = int(parts[-1])
            except ValueError:
                continue
            if bucket < cutoff_bucket:
                try:
                    await client.delete(raw_key)
                    deleted += 1
                except RedisError:
                    # Per-key DEL error → skip; the next sweep tries again.
                    continue
    except RedisError:
        logger.warning(
            "reputation.counters.trim_older_than_24h_all_orgs: Redis "
            "SCAN failed; no rows swept this cycle"
        )
        return 0
    if deleted:
        logger.info("reputation.counters: swept %d stale bucket key(s)", deleted)
    return deleted


__all__ = [
    "BUCKETS_PER_WINDOW",
    "EventKind",
    "incr_counter",
    "sum_last_24h",
    "trim_older_than_24h_all_orgs",
]
