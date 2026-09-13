"""Middleware that populates the per-request `RequestContext` +
raw-body capture for HMAC-signed inbound webhooks.

`TenantContextMiddleware`: in production, the only acceptable
identity source is the `Authorization: Bearer <jwt>` header. The
JWT is decoded by `src.app.core.auth.tokens.decode_token` and its
claims (org_id, user_id, token_id) are pushed into
`RequestContext`.

In development (`IS_DEVELOPMENT=true`), the middleware additionally
honours `X-Org-Id` / `X-User-Id` headers as a fallback when no
`Authorization` header is present. That is how the test suite drives
tenant/user context without minting JWTs.

The middleware never raises — invalid tokens / malformed UUIDs leave
the context empty, and the route's auth dependency
(`get_current_user`) returns 401.

`RawBodyCaptureMiddleware`: for path-prefixed public-ingest routes
we stash the exact bytes of the request body on ``request.state.raw_body``
BEFORE FastAPI's Pydantic parser touches them. HMAC verification
must compare against bit-for-bit what the caller signed — Pydantic's
re-serialisation would flip key order and lose whitespace, breaking
verification. The middleware is path-scoped (only endpoints that
actually verify signatures) so unrelated JSON POSTs don't pay the
memory cost of holding a copy of every request body.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


def _context_from_jwt(
    authorization: str | None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str] | None:
    """Return (org_id, user_id, token_id, scope) if the header carries a valid JWT, else None."""
    if not authorization:
        return None
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw:
        return None
    try:
        claims = decode_token(raw)
    except InvalidToken:
        return None
    return claims.org_id, claims.user_id, claims.token_id, claims.scope


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
        scope: str | None = None

        jwt_claims = _context_from_jwt(request.headers.get("authorization"))
        if jwt_claims is not None:
            org_id, user_id, token_id, scope = jwt_claims
        elif IS_DEVELOPMENT:
            org_id, user_id = _context_from_dev_headers(request)
            # Dev-header fallback is admin-only — staff tokens are
            # always JWT-backed even in dev.
            scope = "admin" if org_id is not None else None

        token = set_context(
            RequestContext(
                org_id=org_id,
                user_id=user_id,
                token_id=token_id,
                request_id=request_id,
                scope=scope,
            )
        )
        try:
            response = await call_next(request)
        finally:
            reset_context(token)

        response.headers["X-Request-Id"] = request_id
        return response


# --- Raw-body capture for HMAC-signed inbound webhooks --------------------
#
# ASGI-level middleware (not BaseHTTPMiddleware) so we can intercept the
# receive channel and stash the exact bytes on ``scope["state"]``. Using
# BaseHTTPMiddleware would force us to buffer the whole body into memory
# regardless of path — this variant is path-scoped so 99% of routes see
# no extra work.


# Cap the raw-body buffer at 512 KB. Custom-event payloads are capped
# at 64 KB in Step 5's validator; 512 KB is a safety headroom for
# webhook providers that pad with metadata. Anything larger is
# refused with 413 before hitting the route.
_RAW_BODY_MAX_BYTES = 512 * 1024


class RawBodyCaptureMiddleware:
    """Capture request body bytes on paths matching one of
    ``path_prefixes`` so downstream HMAC verifiers can read them via
    ``request.state.raw_body``.

    Reads all body chunks up-front, concatenates them, stashes the
    result on the request scope, then re-emits the chunks so the
    downstream ASGI app sees an unmodified stream. Bodies larger than
    ``_RAW_BODY_MAX_BYTES`` short-circuit with a 413 response — this
    guards against a malicious caller streaming multi-GB into the
    handler.

    The middleware is deliberately path-scoped: unrelated JSON POSTs
    don't pay the memory-copy cost, and streaming file uploads
    (``/uploads``, ``/attachments``) pass through untouched.
    """

    def __init__(self, app: ASGIApp, path_prefixes: tuple[str, ...]) -> None:
        self.app = app
        # Store as tuple so ``startswith`` accepts it directly.
        self._prefixes = tuple(path_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self._prefixes):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                # Disconnect during body read — propagate the message
                # so downstream can handle cleanup.
                await self.app(scope, _replay_receive(chunks, message), send)
                return
            chunk = message.get("body", b"") or b""
            total += len(chunk)
            if total > _RAW_BODY_MAX_BYTES:
                await _send_413(send)
                return
            chunks.append(chunk)
            more_body = bool(message.get("more_body", False))

        raw_body = b"".join(chunks)
        state = scope.setdefault("state", {})
        state["raw_body"] = raw_body

        await self.app(scope, _replay_body(raw_body), send)


def _replay_body(raw_body: bytes) -> Receive:
    """Return an ASGI ``receive`` callable that yields the buffered
    body as a single ``http.request`` message, then blocks forever
    on subsequent calls (Starlette's request-body reader stops after
    ``more_body=False``)."""
    delivered = False

    async def _receive() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}
        # If the downstream tries to receive again after the body is
        # exhausted, we hand it an empty tail. Starlette's request
        # helpers never re-enter this path in practice.
        return {"type": "http.request", "body": b"", "more_body": False}

    return _receive


def _replay_receive(chunks: list[bytes], trailing: Message) -> Receive:
    """Rare-path helper: mid-body disconnect. Re-emit whatever we
    already read, then hand the disconnect message to the app so it
    can log + return the appropriate status."""
    sent_index = 0

    async def _receive() -> Message:
        nonlocal sent_index
        if sent_index < len(chunks):
            chunk = chunks[sent_index]
            sent_index += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": sent_index < len(chunks),
            }
        return trailing

    return _receive


async def _send_413(send: Send) -> None:
    """Emit a 413 Content Too Large response. Uses plain-text body so
    non-JSON callers (curl smoke tests, misbehaving webhook providers)
    still see the reason.
    """
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b"Request body too large.",
            "more_body": False,
        }
    )
