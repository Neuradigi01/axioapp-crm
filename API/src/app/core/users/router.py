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
from src.app.core.users.offboarding import (
    compute_open_records_counts,
    transfer_records,
)
from src.app.core.users.schemas import (
    MeUpdate,
    OpenRecordsCounts,
    OrgSummary,
    PasswordChange,
    TransferRecordsRequest,
    TransferRecordsResponse,
    UserCreate,
    UserMe,
    UserOut,
    UserStatusUpdate,
    UserUpdate,
)
from src.app.core.users.service import (
    change_password,
    create_user,
    list_users,
    set_user_status,
    update_self,
    update_user,
)
from src.app.shared.context import get_context
from src.app.shared.db import get_db

router = APIRouter(prefix="/users", tags=["Users"])


@router.patch("/me", response_model=UserOut)
async def patch_me_endpoint(
    payload: MeUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    """Self-service profile edit — name + phone only."""
    updated = await update_self(session, user=user, payload=payload)
    return UserOut.model_validate(updated)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password_endpoint(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Change the current user's password. Optionally revoke other sessions."""
    ctx = get_context()
    await change_password(
        session,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        sign_out_others=payload.sign_out_others,
        current_token_id=ctx.token_id,
    )


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
        needs_onboarding=(org.template_id == "pending"),
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


# --- Offboarding endpoints --------------------------------------------------


@router.get(
    "/{user_id}/open-records-counts",
    response_model=OpenRecordsCounts,
)
async def open_records_counts_endpoint(
    user_id: uuid.UUID,
    _user: User = Depends(require_permissions("users.read")),
    session: AsyncSession = Depends(get_db),
) -> OpenRecordsCounts:
    """Per-entity open-record counts for one user — feeds the
    deactivation modal so the admin can see what would need to be
    transferred. The five entities counted: contacts, leads,
    walk_ins, appointments, tasks. See `offboarding.py` for the
    "open" predicates."""
    counts = await compute_open_records_counts(
        session, user_uuid=user_id, org_id=_user.org_id
    )
    return OpenRecordsCounts(
        user_id=user_id,
        contacts=counts["contacts"],
        leads=counts["leads"],
        walk_ins=counts["walk_ins"],
        appointments=counts["appointments"],
        tasks=counts["tasks"],
        total=counts["total"],
    )


@router.post(
    "/{user_id}/transfer-records",
    response_model=TransferRecordsResponse,
)
async def transfer_records_endpoint(
    user_id: uuid.UUID,
    payload: TransferRecordsRequest,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> TransferRecordsResponse:
    """Atomic bulk-reassign of every open record across the named
    entities (defaults to all five). Each transferred row gets a
    `reassign` audit activity carrying the optional `reason`."""
    entities = payload.normalised_entities()
    summary = await transfer_records(
        session,
        from_user_uuid=user_id,
        to_user_uuid=payload.to_user_id,
        org_id=user.org_id,
        entities=entities,
        reason=payload.reason,
        actor_user_uuid=user.legacy_uuid,
    )
    return TransferRecordsResponse(
        from_user_id=user_id,
        to_user_id=payload.to_user_id,
        transferred=summary["transferred"],
        total=summary["total"],
        audit_activities_written=summary["audit_activities_written"],
    )
