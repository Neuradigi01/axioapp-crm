"""HMAC-signed token encoder / decoder for tracking URLs.

Token format:

    <payload>.<signature>

Where:

  * `payload` = `urlsafe_b64(message_id_bytes + b':' + kind_bytes)`
    — `message_id_bytes` are the 16-byte UUID, `kind_bytes` is the
    single ASCII char `'o' / 'c' / 'u'`.
  * `signature` = `urlsafe_b64(hmac_sha256(payload_b64_bytes, key)[:16])`
    — first 16 bytes of the digest, base64-encoded. 16 bytes is
    enough to make tampering forgery infeasible while keeping the
    token short (URLs go into email HTML; shorter is better).

The output is URL-safe (no padding, no `+`/`/`) and reasonably short
(roughly 50 chars). Tampered tokens fail the constant-time signature
compare and `decode()` returns `None` — the router treats `None` as
a 404 with no further DB lookup.

The signing key comes from `TRACKING_HMAC_KEY` env var; missing or
empty key in dev raises on first encode/decode so misconfiguration is
loud, not silent.
"""
from __future__ import annotations

import base64
import hmac
import os
import uuid
from hashlib import sha256
from typing import Literal, Optional


TokenKind = Literal["o", "c", "u"]
_VALID_KINDS: tuple[TokenKind, ...] = ("o", "c", "u")
_SIG_BYTES = 16  # First 16 bytes of HMAC-SHA256.


class _MissingKey(RuntimeError):
    """Raised at module use time when TRACKING_HMAC_KEY is unset."""


def _get_key() -> bytes:
    raw = os.environ.get("TRACKING_HMAC_KEY", "").strip()
    if not raw:
        raise _MissingKey(
            "TRACKING_HMAC_KEY is not set — tracking links cannot be "
            "encoded or decoded. Configure it in your environment "
            "(see .env.example)."
        )
    return raw.encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(s: str) -> bytes:
    # Restore padding for `base64.urlsafe_b64decode`.
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def encode(*, message_id: uuid.UUID, kind: TokenKind) -> str:
    """Encode a (message_id, kind) tuple to a URL-safe HMAC-signed token.

    Raises `_MissingKey` if `TRACKING_HMAC_KEY` is unset.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"Unknown token kind: {kind!r}")
    payload = message_id.bytes + b":" + kind.encode("ascii")
    payload_b64 = _b64(payload)
    sig = hmac.new(
        _get_key(), payload_b64.encode("ascii"), sha256
    ).digest()[:_SIG_BYTES]
    return f"{payload_b64}.{_b64(sig)}"


def decode(token: str) -> Optional[dict[str, object]]:
    """Decode + verify a token. Returns `{message_id, kind}` on success
    or `None` on any failure (malformed, tampered, unknown kind).

    The single `None`-return contract keeps callers simple: any failure
    path is treated as "not a valid token, render 404"."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    if not payload_b64 or not sig_b64:
        return None

    try:
        expected_sig = hmac.new(
            _get_key(), payload_b64.encode("ascii"), sha256
        ).digest()[:_SIG_BYTES]
        provided_sig = _b64_decode(sig_b64)
    except (_MissingKey, ValueError):
        return None
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, provided_sig):
        return None

    try:
        payload = _b64_decode(payload_b64)
    except (ValueError, Exception):
        return None
    if len(payload) != 16 + 1 + 1 or payload[16:17] != b":":
        return None
    kind_byte = payload[17:18].decode("ascii", errors="replace")
    if kind_byte not in _VALID_KINDS:
        return None
    try:
        message_id = uuid.UUID(bytes=payload[:16])
    except (ValueError, Exception):
        return None
    return {"message_id": message_id, "kind": kind_byte}


__all__ = ["TokenKind", "decode", "encode"]
