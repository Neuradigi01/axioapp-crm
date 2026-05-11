"""FastAPI dependencies for protected routes.

`get_current_user` is the only authentication primitive routes need.
It:
  1. Pulls the decoded JWT claims out of `RequestContext`
     (the middleware put them there).
  2. Verifies the matching `auth_sessions` row exists and isn't
     revoked or expired.
  3. Loads the `User` row (scoped to the org from the token).
  4. Returns it. Any failure → 401.

`require_permissions(*keys)` composes on top of `get_current_user` for
gated routes. It loads the user's role's permission set and checks
every required key is present (admin role with all 4 permissions in
the demo seed passes by default).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.models import AuthSession
from src.app.core.permissions.service import list_permissions_for_role
from src.app.core.users.models import User
from src.app.core.users.service import get_user_by_id
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

    session = (
        await db.execute(select(AuthSession).where(AuthSession.id == ctx.token_id))
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise UNAUTHORIZED
    if session.expires_at <= datetime.now(timezone.utc):
        raise UNAUTHORIZED

    user = await get_user_by_id(db, ctx.user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return user


def require_permissions(*required: str):
    """Returns a dependency that 403s if the user lacks any of the required keys."""

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        granted = {p.key for p in await list_permissions_for_role(db, user.role_id)}
        missing = [k for k in required if k not in granted]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission(s): {', '.join(missing)}",
            )
        return user

    return _check
