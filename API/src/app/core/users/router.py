"""HTTP routes for users.

`GET /users/me` — returns the active user (resolved from
`RequestContext.user_id`, which the middleware populates from the
`X-User-Id` header in dev; Step 1.6 replaces that with a JWT claim).
Bundles the user's role name and granted permission keys so the SPA
can gate UI off a single response.

`GET /users` — admin listing for the active org. Future steps add
filters and admin-only RBAC.

Both routes return 401 if the request has no resolved user/org context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.permissions.service import (
    get_role_by_id,
    list_permissions_for_role,
)
from src.app.core.users.models import User
from src.app.core.users.schemas import UserMe, UserOut
from src.app.core.users.service import list_users
from src.app.shared.db import get_db

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserMe)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserMe:
    role = await get_role_by_id(session, user.role_id)
    permissions = await list_permissions_for_role(session, user.role_id)
    return UserMe(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        role_id=user.role_id,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        role_name=role.name if role else "",
        permission_keys=[p.key for p in permissions],
    )


@router.get("", response_model=list[UserOut])
async def list_users_endpoint(
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    users = await list_users(session, limit=limit, offset=offset)
    return [UserOut.model_validate(u) for u in users]
