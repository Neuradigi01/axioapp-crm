"""FastAPI dependencies for protected routes.

`get_current_user` is the admin-surface primitive (email/password JWT).
It:
  1. Pulls the decoded JWT claims out of `RequestContext`
     (the middleware put them there).
  2. Rejects tokens whose `scope` is not "admin" — a staff PIN token
     must NOT authenticate `/api/v1/...` admin endpoints.
  3. Verifies the matching `auth_sessions` row exists and isn't
     revoked or expired.
  4. Loads the `User` row (scoped to the org from the token).
  5. Returns it. Any failure → 401.

`get_current_staff` is the symmetric primitive for the staff portal.
Same checks but against `staff_sessions` and `scope == "staff"`.

`require_permissions(*keys)` composes on top of `get_current_user` for
gated admin routes. Staff-portal endpoints don't use the RBAC
permission keys — every authenticated staff user can hit them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit, data_access
from src.app.core.permissions.service import list_permissions_for_role
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db


UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    ctx = get_context()
    if ctx.user_id is None or ctx.org_id is None or ctx.token_id is None:
        raise UNAUTHORIZED
    # Staff tokens (scope="staff") must never authenticate admin endpoints.
    if ctx.scope is not None and ctx.scope != "admin":
        raise UNAUTHORIZED

    session = await data_access.get_auth_session(db, session_id=ctx.token_id)
    if session is None or session.revoked_at is not None:
        raise UNAUTHORIZED
    if session.expires_at <= datetime.now(timezone.utc):
        raise UNAUTHORIZED

    user = await data_access.get_user_by_uuid(db, ctx.user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return user


async def get_current_staff(db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the staff-portal session into a `User` row.

    Refuses anything except a JWT with `scope="staff"` that is backed
    by a non-revoked, non-expired `staff_sessions` row. The user is
    also re-checked for `is_active=True`.
    """
    from src.app.core.staff_portal.models import StaffSession

    ctx = get_context()
    if ctx.user_id is None or ctx.org_id is None or ctx.token_id is None:
        raise UNAUTHORIZED
    if ctx.scope != "staff":
        raise UNAUTHORIZED

    session = (
        await db.execute(
            select(StaffSession).where(StaffSession.id == ctx.token_id)
        )
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise UNAUTHORIZED
    if session.expires_at <= datetime.now(timezone.utc):
        raise UNAUTHORIZED

    user = await data_access.get_user_by_uuid(db, ctx.user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return user


def require_permissions(*required: str):
    """Returns a dependency that 403s if the user lacks any of the required keys.

    Emits an `auth.access_denied` audit row before raising 403 so an
    auditor can see who tried what. The row writes to the caller's org
    (the resource lives there — that's the RLS scope that matters).
    `audit.log` is best-effort and never raises, so the 403 always fires
    whether or not the audit row landed.
    """

    async def _check(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        granted = {p.key for p in await list_permissions_for_role(db, user.role_id)}
        missing = [k for k in required if k not in granted]
        if missing:
            await audit.log(
                "auth.access_denied",
                entity_type="access_attempt",
                after={
                    "path": request.url.path,
                    "method": request.method,
                    "required_permission_keys": list(required),
                    "missing_permission_keys": missing,
                    "status_code": 403,
                },
                ip=request.client.host if request.client else None,
                ua=request.headers.get("user-agent"),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission(s): {', '.join(missing)}",
            )
        return user

    return _check
