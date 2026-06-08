"""Subscription-state middleware — Step 10.

Blocks every mutating HTTP verb (POST / PUT / PATCH / DELETE) for orgs
whose subscription status is one of `read_only`, `past_due`,
`archived`, or `cancelled`. Read verbs (GET / HEAD / OPTIONS) always
pass; so do a tight, explicit allow-list of write paths that are the
recovery flow or identity-level (logout, profile, exports, …).

Order is set in `main.py`:

    app.add_middleware(CORSMiddleware, ...)          # innermost on request
    app.add_middleware(SubscriptionStateMiddleware)  # middle
    app.add_middleware(TenantContextMiddleware)      # outermost on request

`TenantContextMiddleware` runs first and populates `RequestContext`
with `org_id` from the JWT. This middleware then reads that context
to decide whether to block — there is no JWT decoding here.

Response shape for a blocked write (HTTP 402):

    {
      "reason": "read_only",                    # or past_due / archived / cancelled
      "subscription_status": "read_only",
      "since": "2026-06-19T10:00:00Z",          # nullable for past_due
      "message": "Your trial has ended. Upgrade to continue using FurnitureCRM.",
      "upgrade_url": "/user/settings/billing"
    }
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Look up `async_session` at call time via the module attribute so
# the conftest patch (which rebinds `src.core.db.async_session = TestSession`)
# propagates into the middleware during tests.
from src.core import db as _core_db
from src.app.core.subscriptions.models import Subscription
from src.app.shared.context import get_context


# Methods that never block. Reads are unconditionally allowed even on
# `archived` / `cancelled` orgs — they need to be able to inspect
# their billing page, export their data, and read the audit trail.
READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# The set of statuses that trigger a 402 on a non-read non-allow-list
# write. Distinct from `ACTIVE_STATUSES` on the model: `trialing` and
# `active` are NOT blocked; `past_due` and `read_only` are blocked but
# `get_active_subscription` still returns their rows (recovery path).
BLOCKED_STATUSES: frozenset[str] = frozenset(
    {"read_only", "past_due", "archived", "cancelled"}
)

# Paths exempted from the block. Each pattern is anchored end-to-end
# so wildcards do not over-match. The list is intentionally small;
# adding a new entry should be accompanied by a code-review note
# explaining why the path must remain writable on a blocked sub.
_ALLOWLIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/auth/logout$"),
    re.compile(r"^/api/v1/auth/refresh$"),
    re.compile(r"^/api/v1/subscriptions/change$"),
    re.compile(r"^/api/v1/subscriptions/seats$"),
    re.compile(r"^/api/v1/subscriptions/cancel$"),
    re.compile(r"^/api/v1/users/me$"),
    re.compile(r"^/api/v1/users/me/2fa/.+$"),
    re.compile(r"^/api/v1/users/me/sessions/.+$"),
    re.compile(r"^/api/v1/exports/.+$"),
)

# Per-status copy. `read_only` and `past_due` differ in tone because
# the customer's recovery action differs (upgrade vs fix payment).
_BLOCK_MESSAGES: dict[str, str] = {
    "read_only": "Your trial has ended. Upgrade to continue using FurnitureCRM.",
    "past_due": (
        "Your subscription payment is past due. Update your payment method "
        "to restore write access."
    ),
    "archived": "Your account is archived. Contact support to restore.",
    "cancelled": "Your subscription is cancelled.",
}

# Frontend route the 402 redirects to via the `upgrade_url` field.
# Constant rather than configurable because the SPA's routing is fixed.
_UPGRADE_URL = "/user/settings/billing"


def _allowlisted(path: str) -> bool:
    return any(pattern.match(path) for pattern in _ALLOWLIST_PATTERNS)


async def _latest_subscription_state(
    session: AsyncSession, org_id: uuid.UUID,
) -> tuple[str | None, datetime | None]:
    """Return `(status, since)` for the most-recent subscription row.

    "Most-recent" means highest `created_at`. Uses a single row even
    when the org has stacked archived/cancelled history — the latest
    row represents the current operational state.

    The `since` value is filled from `read_only_at` / `archived_at` /
    `cancelled_at` depending on status. `past_due` has no dedicated
    timestamp column so it returns `None` there; the UI falls back to
    a generic "since recently" copy in that case.
    """
    sub = (
        await session.execute(
            select(Subscription)
            .where(Subscription.org_id == org_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if sub is None:
        return None, None
    since: datetime | None = None
    if sub.status == "read_only":
        since = sub.read_only_at
    elif sub.status == "archived":
        since = sub.archived_at
    elif sub.status == "cancelled":
        since = sub.cancelled_at
    return sub.status, since


def _build_block_body(status: str, since: datetime | None) -> dict:
    return {
        "reason": status,
        "subscription_status": status,
        "since": since.isoformat() if since is not None else None,
        "message": _BLOCK_MESSAGES.get(
            status, "Write access is currently blocked."
        ),
        "upgrade_url": _UPGRADE_URL,
    }


class SubscriptionStateMiddleware(BaseHTTPMiddleware):
    """Refuses mutating requests when the caller's subscription is in a
    write-locked state.

    The middleware does NO authentication of its own — that work is
    done upstream by `TenantContextMiddleware` and by per-route
    `get_current_user` dependencies. When `RequestContext.org_id` is
    `None` (anonymous / pre-login surfaces like signup) the middleware
    passes the request through; the per-route auth dependency then
    decides whether the call is legitimate.
    """

    async def dispatch(
        self, request: Request, call_next,
    ) -> Response:
        if request.method in READ_METHODS:
            return await call_next(request)

        ctx = get_context()
        if ctx.org_id is None:
            # Anonymous request — let the route's auth dependency handle
            # it. There's no org to gate against here.
            return await call_next(request)

        if _allowlisted(request.url.path):
            return await call_next(request)

        # Open a fresh session for the entitlements lookup. One extra
        # round-trip per mutating call on a blocked org; the Step 7
        # composed read path optimises read traffic, this path
        # optimises correctness over latency.
        async with _core_db.async_session() as session:
            status_value, since = await _latest_subscription_state(
                session, ctx.org_id,
            )

        if status_value is None or status_value not in BLOCKED_STATUSES:
            return await call_next(request)

        return JSONResponse(
            status_code=402,
            content=_build_block_body(status_value, since),
        )
