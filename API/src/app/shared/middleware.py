"""Middleware that populates the per-request `RequestContext`.

For each incoming HTTP request:
  1. Generate a request ID (or reuse `X-Request-Id` if the client sent one).
  2. Read the dev-only `X-Org-Id` and `X-User-Id` headers to populate
     `org_id` and `user_id`.
     (Step 1.6 will replace these with JWT-claim extraction.)
  3. Set the contextvar so anything downstream can call `get_context()`.
  4. After the response, reset the contextvar.

The middleware never raises — a malformed UUID header is treated as "no
context value", and the request continues normally. Endpoints that
require a valid org/user context must enforce that themselves (auth
dependency in Step 1.6).
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.app.shared.context import RequestContext, reset_context, set_context


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex

        org_id = _parse_uuid(request.headers.get("x-org-id"))
        user_id = _parse_uuid(request.headers.get("x-user-id"))

        token = set_context(
            RequestContext(org_id=org_id, user_id=user_id, request_id=request_id)
        )
        try:
            response = await call_next(request)
        finally:
            reset_context(token)

        response.headers["X-Request-Id"] = request_id
        return response
