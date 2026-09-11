"""HMAC-SHA256 signature + nonce verification.

Extracted from ``core/integrations/meta/webhook._verify_signature``
into a shared helper so custom-events ingest, Stripe / Twilio inbound
webhooks (future), and any other signed-body surface can share one
audited implementation. Callers pass raw bytes + the header/secret
values; the helper handles the constant-time compare, the
``sha256=`` prefix strip, and the timestamp / nonce checks.

Two entry points:

  * ``verify_signature`` — synchronous, no I/O. Verifies HMAC +
    optional timestamp window. Use when replay defense is provided
    by the payload itself (e.g. Meta's ``X-Hub-Signature-256`` — Meta
    signs the same body once and does NOT re-sign on retry, so a
    replay presents an old body which the caller already stored and
    can reject at the DB level).

  * ``verify_signature_with_nonce`` — async, uses Redis SETNX to
    reject replays within the signature window. Use when the payload
    can be legitimately identical across two calls (custom-event
    ingest: same event definition, same idem key, same payload —
    replay defense must be at the transport layer).

Both return a ``VerifyResult`` with a short reason string so callers
can wire the failure into their audit event without pattern-matching
on booleans.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Default signature window: 5 minutes on either side of "now". Meta
# uses ~5min; Stripe/Slack use 5min ± clock skew. Ours matches so
# callers don't have to remember which surface uses what.
_DEFAULT_WINDOW_SECONDS = 300
_DEFAULT_CLOCK_SKEW_SECONDS = 150


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of a verify call. ``reason`` is always set — it's the
    string the caller writes to the audit event or the 401 body.
    """

    ok: bool
    reason: str


_REASON_OK = "signature_ok"
_REASON_MISSING_SIG = "missing_signature_header"
_REASON_MISSING_SECRET = "missing_secret"
_REASON_MISSING_TIMESTAMP = "missing_timestamp_header"
_REASON_TIMESTAMP_INVALID = "timestamp_invalid"
_REASON_TIMESTAMP_OUT_OF_WINDOW = "timestamp_out_of_window"
_REASON_BAD_SIGNATURE = "bad_signature"
_REASON_REPLAY = "replay_nonce_seen"
_REASON_MISSING_NONCE = "missing_nonce_header"
_REASON_REDIS_UNAVAILABLE = "redis_unavailable_nonce_cache"


def _extract_hex_digest(signature_header: str) -> str | None:
    """Accept both raw hex (``a1b2c3...``) and ``sha256=<hex>`` forms.

    Slack / Segment / Stripe all use the prefixed form; some
    hand-rolled clients emit the raw hex. Both are 64 chars; anything
    else is rejected."""
    if not signature_header:
        return None
    candidate = signature_header.strip()
    if candidate.startswith("sha256="):
        candidate = candidate.split("=", 1)[1]
    if len(candidate) != 64:
        return None
    try:
        int(candidate, 16)
    except ValueError:
        return None
    return candidate.lower()


def _parse_unix_timestamp(raw: str | None) -> int | None:
    """Accept seconds-since-epoch as int or float string. Reject
    negatives, values above ``2^32 - 1`` (year 2106), and non-numeric
    input."""
    if not raw:
        return None
    try:
        value = int(float(raw.strip()))
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 0xFFFFFFFF:
        return None
    return value


def _within_window(
    timestamp: int, *, window_seconds: int, clock_skew_seconds: int, now: int
) -> bool:
    """Timestamp must be within ``[now - window - skew, now + skew]``."""
    lo = now - window_seconds - clock_skew_seconds
    hi = now + clock_skew_seconds
    return lo <= timestamp <= hi


def _compute_signature(
    *, raw_body: bytes, secret: str, timestamp_header: str | None
) -> str:
    """Compute the expected hex digest. When a timestamp header value
    is provided it's prefixed to the body — Stripe / Slack pattern
    (``t=<ts>.<body>``) so a signature captured for one moment cannot
    be reused with a different timestamp."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    if timestamp_header is not None:
        mac.update(timestamp_header.encode("utf-8"))
        mac.update(b".")
    mac.update(raw_body)
    return mac.hexdigest()


def verify_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str | None,
    timestamp_header: str | None = None,
    window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    clock_skew_seconds: int = _DEFAULT_CLOCK_SKEW_SECONDS,
    now: int | None = None,
) -> VerifyResult:
    """Verify an HMAC-SHA256 signature over ``raw_body``.

    When ``timestamp_header`` is provided:
      * the timestamp must be within
        ``[now - window - skew, now + skew]``,
      * the signature is computed over ``f"{timestamp}.{body}"`` so
        an attacker cannot present an old signature with a fresh
        timestamp.

    When ``timestamp_header`` is None, only the raw body is signed
    (Meta-style webhooks — replay defense comes from the payload).

    Constant-time compare. Missing/empty header/secret → ``ok=False``
    with a specific reason; no exception ever escapes.
    """
    if not secret:
        return VerifyResult(ok=False, reason=_REASON_MISSING_SECRET)

    hex_digest = _extract_hex_digest(signature_header or "")
    if hex_digest is None:
        return VerifyResult(ok=False, reason=_REASON_MISSING_SIG)

    if timestamp_header is not None:
        ts = _parse_unix_timestamp(timestamp_header)
        if ts is None:
            return VerifyResult(ok=False, reason=_REASON_TIMESTAMP_INVALID)
        current = now if now is not None else int(time.time())
        if not _within_window(
            ts,
            window_seconds=window_seconds,
            clock_skew_seconds=clock_skew_seconds,
            now=current,
        ):
            return VerifyResult(ok=False, reason=_REASON_TIMESTAMP_OUT_OF_WINDOW)

    expected = _compute_signature(
        raw_body=raw_body, secret=secret, timestamp_header=timestamp_header
    )
    if hmac.compare_digest(expected, hex_digest):
        return VerifyResult(ok=True, reason=_REASON_OK)
    return VerifyResult(ok=False, reason=_REASON_BAD_SIGNATURE)


async def verify_signature_with_nonce(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str | None,
    timestamp_header: str | None,
    nonce_header: str | None,
    scope: str,
    window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    clock_skew_seconds: int = _DEFAULT_CLOCK_SKEW_SECONDS,
    now: int | None = None,
) -> VerifyResult:
    """HMAC verify + Redis nonce cache.

    ``scope`` is a short label (``"events"``, ``"webhook:stripe"``,
    ...) — becomes the Redis prefix so distinct surfaces cannot
    collide. Nonces are stored with TTL =
    ``window_seconds + clock_skew_seconds + 60`` so a nonce cannot
    be replayed even if the caller re-sends right at the window edge.

    On Redis outage: fails CLOSED with reason
    ``redis_unavailable_nonce_cache``. Callers surface as 503.
    """
    if not nonce_header or not isinstance(nonce_header, str) or not nonce_header.strip():
        return VerifyResult(ok=False, reason=_REASON_MISSING_NONCE)

    result = verify_signature(
        raw_body=raw_body,
        signature_header=signature_header,
        secret=secret,
        timestamp_header=timestamp_header,
        window_seconds=window_seconds,
        clock_skew_seconds=clock_skew_seconds,
        now=now,
    )
    if not result.ok:
        return result

    from src.app.shared import rate_limit_shared

    client = rate_limit_shared._redis()
    if client is None:
        return VerifyResult(ok=False, reason=_REASON_REDIS_UNAVAILABLE)

    ttl = window_seconds + clock_skew_seconds + 60
    # Bound nonce length to defeat pathological inputs; 128 chars is
    # plenty for any UUID / random hex / Slack request-id.
    trimmed = nonce_header.strip()[:128]
    redis_key = f"pi:nonce:{scope}:{trimmed}"
    try:
        won = await client.set(redis_key, "1", nx=True, ex=ttl)
    except Exception as exc:  # pragma: no cover — Redis outage
        logger.warning(
            "verify_signature_with_nonce: redis error %s (scope=%s)", exc, scope
        )
        return VerifyResult(ok=False, reason=_REASON_REDIS_UNAVAILABLE)

    if not won:
        return VerifyResult(ok=False, reason=_REASON_REPLAY)
    return VerifyResult(ok=True, reason=_REASON_OK)


__all__ = [
    "VerifyResult",
    "verify_signature",
    "verify_signature_with_nonce",
]
