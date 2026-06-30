"""Per-request context for multi-tenant isolation.

The `RequestContext` carries the resolved `org_id`, `user_id`, and a
`request_id` for correlation. It lives in a `ContextVar` so any code
downstream of the middleware (services, ORM hooks, loggers) can pick
it up without explicit threading through call signatures.

Today the org_id is read from a dev placeholder header (`X-Org-Id`).
Step 1.6 replaces this with JWT-claim extraction.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    token_id: uuid.UUID | None = None
    request_id: str | None = None
    # "admin" or "staff" — set from the JWT `scope` claim by
    # `TenantContextMiddleware`. Auth dependencies use this to refuse
    # cross-surface tokens (admin JWT against /staff-portal endpoints
    # and vice versa).
    scope: str | None = None


_request_context: ContextVar[RequestContext] = ContextVar(
    "request_context",
    default=RequestContext(),
)


def get_context() -> RequestContext:
    """Return the current request context (empty if not set)."""
    return _request_context.get()


def set_context(ctx: RequestContext):
    """Set the current request context. Returns a token for resetting later."""
    return _request_context.set(ctx)


def reset_context(token) -> None:
    """Reset the context using a token returned from `set_context`."""
    _request_context.reset(token)
