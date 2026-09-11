"""Redis-backed idempotency store for public-ingest endpoints.

Two-phase protocol so a caller with a slow processing step (contact
create, workflow fanout) can't have a second caller see the same
Idempotency-Key succeed twice:

  1. ``check_and_reserve(scope_key, ttl)`` — atomically ``SETNX`` a
     ``PENDING`` marker. First caller: returns ``is_replay=False``,
     ``cached_response=None`` — proceed with processing.
     Subsequent caller before the first stores a result: returns
     ``is_replay=True``, ``cached_response=None`` — respond 425
     "processing, retry".
     Subsequent caller after the first stores a result: returns
     ``is_replay=True``, ``cached_response=<parsed>`` — echo the
     stored response body.

  2. ``store_response(scope_key, payload, ttl)`` — replace the
     ``PENDING`` marker with a JSON-serialised response body so
     retries see the exact same reply. Extends the TTL to the full
     window (default 24h) from the store time.

Keys are validated against a strict regex before touching Redis so a
caller can't blow up the keyspace with pathological values (unicode
tricks, URL-encoded newlines, 4KB of A's). Scope keys are namespaced
by ``(org_id, api_key_id, idempotency_key)`` so two orgs (or two keys
in the same org) can safely reuse the same idempotency key without
colliding.

Fail-mode: on Redis outage the store fails closed for the
``check_and_reserve`` path (caller sees 503 — we cannot guarantee
uniqueness). ``store_response`` degrades to a no-op with a warning
log — the caller has already committed the DB write, so the miss
just means the next retry re-runs the workflow; the DB layer catches
duplicates via unique constraints anyway.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Match Stripe / Segment: 1..128 chars, printable ASCII, no leading /
# trailing whitespace, no control chars. Rejected keys 400 out with a
# clear error so integrations can fix their client. HubSpot uses the
# even-stricter ``[A-Za-z0-9_-]`` — we allow a couple more separators
# (``.:``) so callers can encode ``run_id.attempt`` or
# ``pipeline:step`` naturally.
_IDEM_KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")

# ``PENDING`` sentinel value stored under a reserved slot before the
# caller finishes processing. Kept distinct from any legitimate JSON
# body (starts with ``!`` which is not a valid JSON start char).
_PENDING = "!PENDING"

_DEFAULT_TTL_SECONDS = 24 * 3600  # 24h


class InvalidIdempotencyKey(ValueError):
    """Raised when the caller-provided key fails the regex gate."""


@dataclass(frozen=True, slots=True)
class IdempotencyResult:
    """Outcome of ``check_and_reserve``.

    * ``is_replay=False`` — first-time; caller should process the
      request. ``cached_response`` is ``None``.
    * ``is_replay=True``, ``cached_response=<dict>`` — completed
      replay; echo the stored response.
    * ``is_replay=True``, ``cached_response=None`` — in-flight replay;
      caller responds 425 (Too Early) with a Retry-After hint. This
      case is rare (a bug or a very slow first request) but must not
      double-process.
    """

    is_replay: bool
    cached_response: dict[str, Any] | None


def _validate_key(idempotency_key: str) -> None:
    if not isinstance(idempotency_key, str) or not _IDEM_KEY_RE.match(idempotency_key):
        raise InvalidIdempotencyKey(
            "Idempotency-Key must be 1-128 chars, [A-Za-z0-9_.:-] only."
        )


def _redis_key(*, org_id: uuid.UUID, api_key_id: uuid.UUID, idempotency_key: str) -> str:
    return f"pi:idem:{org_id}:{api_key_id}:{idempotency_key}"


async def check_and_reserve(
    *,
    org_id: uuid.UUID,
    api_key_id: uuid.UUID,
    idempotency_key: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> IdempotencyResult:
    """Reserve the slot for this ``(org, key, idem)`` triple.

    Raises ``InvalidIdempotencyKey`` when the caller-provided key
    fails the regex gate. Raises ``RuntimeError`` on Redis outage so
    the caller sees 503 rather than silently double-processing.
    """
    _validate_key(idempotency_key)

    from src.app.shared import rate_limit_shared  # shared aioredis client

    client = rate_limit_shared._redis()
    if client is None:
        # Fail-closed — we cannot uphold the uniqueness guarantee.
        # Callers wrap this in a 503 + Retry-After.
        raise RuntimeError("Redis unavailable — idempotency reserve failed")

    redis_key = _redis_key(
        org_id=org_id, api_key_id=api_key_id, idempotency_key=idempotency_key
    )
    try:
        # SETNX with TTL — atomic "reserve if free". Return value is
        # True when we won (first time), False when the slot already
        # held some value.
        won = await client.set(redis_key, _PENDING, nx=True, ex=ttl_seconds)
        if won:
            return IdempotencyResult(is_replay=False, cached_response=None)

        existing = await client.get(redis_key)
    except Exception as exc:  # pragma: no cover — Redis outage path
        logger.warning(
            "idempotency check_and_reserve: redis error %s (key=%s)", exc, redis_key
        )
        raise RuntimeError("Redis unavailable — idempotency reserve failed") from exc

    if existing is None:
        # Race: another caller may have set-then-expired between our
        # SETNX and GET. Treat as first-time and retry the reserve —
        # a second collision is astronomically unlikely and, if it
        # happens, we'll return is_replay=True on the next line.
        won_retry = await client.set(redis_key, _PENDING, nx=True, ex=ttl_seconds)
        if won_retry:
            return IdempotencyResult(is_replay=False, cached_response=None)
        existing = await client.get(redis_key)
        if existing is None:
            # Give up — treat as replay-in-flight so the caller sees 425.
            return IdempotencyResult(is_replay=True, cached_response=None)

    if isinstance(existing, bytes):
        existing = existing.decode("utf-8", errors="replace")

    if existing == _PENDING:
        return IdempotencyResult(is_replay=True, cached_response=None)

    try:
        payload = json.loads(existing)
    except json.JSONDecodeError:
        # Stale value from an earlier bug — treat as pending replay
        # so the client is told to retry rather than served garbage.
        logger.warning(
            "idempotency: non-JSON stored payload for key=%s; forcing 425 replay",
            redis_key,
        )
        return IdempotencyResult(is_replay=True, cached_response=None)

    if not isinstance(payload, dict):
        return IdempotencyResult(is_replay=True, cached_response=None)
    return IdempotencyResult(is_replay=True, cached_response=payload)


async def store_response(
    *,
    org_id: uuid.UUID,
    api_key_id: uuid.UUID,
    idempotency_key: str,
    response_payload: dict[str, Any],
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Persist the response body so retries within ``ttl_seconds``
    echo it back. Called after the caller's processing step commits.

    Best-effort on Redis outage: logs + no-ops. The DB layer's unique
    constraints catch true duplicates; this store is a
    latency-optimisation, not the correctness gate.
    """
    _validate_key(idempotency_key)

    from src.app.shared import rate_limit_shared

    client = rate_limit_shared._redis()
    if client is None:
        logger.warning(
            "idempotency store_response: redis unavailable (org=%s idem=%s)",
            org_id,
            idempotency_key,
        )
        return

    redis_key = _redis_key(
        org_id=org_id, api_key_id=api_key_id, idempotency_key=idempotency_key
    )
    try:
        await client.set(redis_key, json.dumps(response_payload), ex=ttl_seconds)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "idempotency store_response: redis error %s (key=%s)", exc, redis_key
        )


async def clear_for_tests(
    *,
    org_id: uuid.UUID,
    api_key_id: uuid.UUID,
    idempotency_key: str,
) -> None:
    """Test hook — delete the slot so a re-run of the same test
    doesn't see the previous invocation's cached response."""
    from src.app.shared import rate_limit_shared

    client = rate_limit_shared._redis()
    if client is None:
        return
    redis_key = _redis_key(
        org_id=org_id, api_key_id=api_key_id, idempotency_key=idempotency_key
    )
    try:
        await client.delete(redis_key)
    except Exception:  # pragma: no cover — defensive
        pass


__all__ = [
    "IdempotencyResult",
    "InvalidIdempotencyKey",
    "check_and_reserve",
    "clear_for_tests",
    "store_response",
]
