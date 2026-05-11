"""JWT encode/decode for the layered auth.

Uses python-jose (already a dependency for the legacy auth) with HS256
and the shared `JWT_SECRET_KEY` from `config`. Token payload carries
the three claims every downstream module reads off `RequestContext`:

  sub       — user_id (UUID string)
  org_id    — UUID string
  token_id  — UUID string; PK of the matching `auth_sessions` row,
              used to revoke the session without invalidating the
              shared HMAC key.
  iat / exp — issuance + expiry (UTC, seconds since epoch).

`decode_token` raises `InvalidToken` for any of: malformed JWT, bad
signature, expired, or missing required claim. The middleware catches
this and leaves the request context empty (the auth dependency then
returns 401).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from config import JWT_ALGORITHM, JWT_SECRET_KEY

ACCESS_TOKEN_TTL = timedelta(hours=24)


class InvalidToken(Exception):
    """Raised when a JWT can't be decoded, has a bad signature, expired, or is missing claims."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    org_id: uuid.UUID
    token_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime


def encode_token(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    token_id: uuid.UUID,
    now: datetime | None = None,
    ttl: timedelta = ACCESS_TOKEN_TTL,
) -> tuple[str, datetime]:
    """Return (jwt, expires_at)."""
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + ttl
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "token_id": str(token_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded, expires_at


def decode_token(raw: str) -> TokenClaims:
    """Decode a JWT into typed `TokenClaims`. Raises `InvalidToken` on any failure."""
    try:
        payload = jwt.decode(raw, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc

    try:
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org_id"]),
            token_id=uuid.UUID(payload["token_id"]),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidToken(f"missing or malformed claim: {exc}") from exc
