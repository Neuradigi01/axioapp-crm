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

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.permissions.service import (
    get_role_by_id,
    list_permissions_for_role,
)
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.core.users.schemas import (
    OrgSummary,
    UserCreate,
    UserMe,
    UserOut,
    UserStatusUpdate,
    UserUpdate,
)
from src.app.core.users.service import (
    create_user,
    list_users,
    set_user_status,
    update_user,
)
from src.app.shared.db import get_db

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserMe)
async def get_me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserMe:
    role = await get_role_by_id(session, user.role_id)
    permissions = await list_permissions_for_role(session, user.role_id)
    org = (
        await session.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
    ).scalar_one()
    return UserMe(
        # `user.id` is the bigint storage PK of tbl_user_login (DR.6.3).
        # The UUID identity exposed to consumers is `user.legacy_uuid`.
        id=user.legacy_uuid,
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
        org=OrgSummary.model_validate(org),
    )


@router.get("", response_model=list[UserOut])
async def list_users_endpoint(
    limit: int = 50,
    offset: int = 0,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    users = await list_users(
        session, org_id=_user.org_id, limit=limit, offset=offset
    )
    return [UserOut.model_validate(u) for u in users]


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_endpoint(
    payload: UserCreate,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    new_user = await create_user(session, org_id=user.org_id, payload=payload)
    return UserOut.model_validate(new_user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdate,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    updated = await update_user(
        session, user_id=user_id, org_id=user.org_id, payload=payload
    )
    return UserOut.model_validate(updated)


@router.patch("/{user_id}/status", response_model=UserOut)
async def set_user_status_endpoint(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    updated = await set_user_status(
        session,
        user_id=user_id,
        org_id=user.org_id,
        is_active=payload.is_active,
    )
    return UserOut.model_validate(updated)
