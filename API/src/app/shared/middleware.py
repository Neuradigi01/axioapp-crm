"""Middleware that populates the per-request `RequestContext`.

In production, the only acceptable identity source is the
`Authorization: Bearer <jwt>` header. The JWT is decoded by
`src.app.core.auth.tokens.decode_token` and its claims (org_id,
user_id, token_id) are pushed into `RequestContext`.

In development (`IS_DEVELOPMENT=true`), the middleware additionally
honours `X-Org-Id` / `X-User-Id` headers as a fallback when no
`Authorization` header is present. That is how the test suite drives
tenant/user context without minting JWTs.

The middleware never raises — invalid tokens / malformed UUIDs leave
the context empty, and the route's auth dependency
(`get_current_user`) returns 401.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import IS_DEVELOPMENT
from src.app.core.auth.tokens import InvalidToken, decode_token
from src.app.shared.context import RequestContext, reset_context, set_context


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _context_from_jwt(authorization: str | None) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
    """Return (org_id, user_id, token_id) if the header carries a valid JWT, else None."""
    if not authorization:
        return None
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        return None
    try:
        claims = decode_token(raw)
    except InvalidToken:
        return None
    return claims.org_id, claims.user_id, claims.token_id


def _context_from_dev_headers(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Dev-only fallback. Returns (org_id, user_id) from X-Org-Id / X-User-Id."""
    return (
        _parse_uuid(request.headers.get("x-org-id")),
        _parse_uuid(request.headers.get("x-user-id")),
    )


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex

        org_id: uuid.UUID | None = None
        user_id: uuid.UUID | None = None
        token_id: uuid.UUID | None = None

        jwt_claims = _context_from_jwt(request.headers.get("authorization"))
        if jwt_claims is not None:
            org_id, user_id, token_id = jwt_claims
        elif IS_DEVELOPMENT:
            org_id, user_id = _context_from_dev_headers(request)

        token = set_context(
            RequestContext(
                org_id=org_id,
                user_id=user_id,
                token_id=token_id,
                request_id=request_id,
            )
        )
        try:
            response = await call_next(request)
        finally:
            reset_context(token)

        response.headers["X-Request-Id"] = request_id
        return response
