"""Middleware that populates the per-request `RequestContext`.

For each incoming HTTP request:
  1. Generate a request ID (or reuse `X-Request-Id` if the client sent one).
  2. Read the dev-only `X-Org-Id` header to populate `org_id`.
     (Step 1.6 will replace this with JWT-claim extraction.)
  3. Set the contextvar so anything downstream can call `get_context()`.
  4. After the response, reset the contextvar.

The middleware never raises — a malformed UUID header is treated as "no org",
and the request continues normally. Endpoints that require a valid org context
must enforce that themselves (auth dependency in Step 1.6).
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.shared.context import RequestContext, reset_context, set_context


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex

        org_id: uuid.UUID | None = None
        raw_org = request.headers.get("x-org-id")
        if raw_org:
            try:
                org_id = uuid.UUID(raw_org)
            except ValueError:
                org_id = None

        token = set_context(
            RequestContext(org_id=org_id, user_id=None, request_id=request_id)
        )
        try:
            response = await call_next(request)
        finally:
            reset_context(token)

        response.headers["X-Request-Id"] = request_id
        return response
