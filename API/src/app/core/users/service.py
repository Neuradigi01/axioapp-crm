"""Service layer for users.

Writes for the three-table user model (DR.7+):
  - tbl_user_login   → auth row (id bigint, password, is_active, legacy_uuid)
  - tbl_user_info    → profile (member_id, first_name, last_name, email, mobile_no)
  - tbl_organization_members → membership (org_id, role_id, status, is_active, is_demo)

Write paths (create / update / status) always fan out across all three
tables in dependency order. Audit events fire after each successful
write so the team can trace who changed what.

Reads — single-user lookups, membership predicates, role guards, profile
fetches — live in `src.app.core.users.data_access`. This service file
holds orchestration only: transactions, audit, business rules.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit, data_access
from src.app.core.auth.models import AuthSession
from src.app.core.permissions.models import Role
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.core.users.schemas import MeUpdate, UserCreate, UserUpdate
from src.app.shared.audit import log_entity_change
from src.app.shared.security.password import hash_password, verify_password


# --- list (the one read kept here — non-trivial cross-table list query) -


async def list_users(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[User]:
    """List FurnitureCRM users, optionally scoped to an org membership.

    After DR.7 the email + org_membership live on separate tables, so
    we JOIN through tbl_user_info (for ordering by email) and
    tbl_organization_members (for the org filter + active flag).
    """
    stmt = (
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .where(OrganizationMember.is_active.is_(True))
        .order_by(func.lower(UserInfo.email))
        .limit(limit)
        .offset(offset)
    )
    if org_id is not None:
        stmt = stmt.where(OrganizationMember.organization_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- write paths (admin CRUD) -------------------------------------------


def _split_full_name(full_name: str) -> tuple[str, str]:
    """Split `"Jane Doe"` → `("Jane", "Doe")`. Single-word → `("Jane", "")`."""
    parts = full_name.strip().split(maxsplit=1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


async def create_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: UserCreate,
) -> User:
    """Admin-creates a user across all three tables.

    Returns the freshly-inserted `User`. The user can NOT log in until
    they accept an invitation (step 2.5.6 wires that flow). Until then
    we write a random unguessable password so the bcrypt verify path
    can never short-circuit on an empty/NULL hash.
    """
    await data_access.get_role_in_org(
        session, role_id=payload.role_id, org_id=org_id
    )

    if await data_access.email_exists(session, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"email {payload.email} is already in use",
        )

    # The layered `User` mapper excludes the legacy `user_id` text
    # handle and the `two_factor_*` columns (they live on the legacy
    # `UserLogin` mapper) — but both are NOT NULL on `tbl_user_login`.
    # Insert at the table level via `pg_insert` so we can populate
    # them, then load the freshly-inserted row through the layered
    # mapper to get the relationships hydrated.
    new_uuid = uuid.uuid4()
    inserted = (
        await session.execute(
            pg_insert(User.__table__)
            .values(
                legacy_uuid=new_uuid,
                user_id="usr_" + new_uuid.hex,
                password=hash_password(secrets.token_urlsafe(32)),
                is_active=True,
                two_factor_enabled=False,
            )
            .returning(User.__table__.c.id)
        )
    ).scalar_one()
    login = (
        await session.execute(select(User).where(User.id == inserted))
    ).scalar_one()

    first, last = _split_full_name(payload.full_name)
    profile = UserInfo(
        member_id=login.id,
        first_name=first,
        last_name=last,
        email=payload.email,
        mobile_no=payload.phone,
        is_email_verified=False,
        is_mobile_verified=False,
    )
    session.add(profile)

    membership = OrganizationMember(
        organization_id=org_id,
        user_member_id=login.id,
        role_id=payload.role_id,
        status="active",
        is_active=True,
        is_demo=False,
    )
    session.add(membership)

    await session.commit()
    await session.refresh(login)

    await log_entity_change(
        action="users.created",
        entity_type="user",
        entity_id=new_uuid,
        after={
            "email": payload.email,
            "full_name": payload.full_name,
            "role_id": str(payload.role_id),
        },
    )
    return login


async def update_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    payload: UserUpdate,
) -> User:
    """Update name / phone (tbl_user_info) and/or role (tbl_organization_members).

    Raises 404 if the user doesn't have a membership in `org_id`.
    `user_id` is the UUID identity (`tbl_user_login.legacy_uuid`).
    """
    user, membership = await data_access.require_membership(
        session,
        user_uuid=user_id,
        org_id=org_id,
        on_missing=status.HTTP_404_NOT_FOUND,
    )

    profile = await data_access.get_user_info(session, user.id)
    if profile is None:
        # Profile row should always exist for FurnitureCRM users
        # (created by DR.7.2 backfill or `create_user` above), but
        # defend against a partial-write state.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="profile row missing — data inconsistency",
        )

    before_role_id = membership.role_id
    before = {
        "full_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "phone": profile.mobile_no,
        "role_id": str(membership.role_id),
    }

    changes = payload.model_dump(exclude_unset=True)
    role_changed = False
    new_role: Role | None = None

    if "full_name" in changes and changes["full_name"] is not None:
        first, last = _split_full_name(changes["full_name"])
        profile.first_name = first
        profile.last_name = last
    if "phone" in changes:
        profile.mobile_no = changes["phone"]
    if "role_id" in changes and changes["role_id"] is not None:
        new_role = await data_access.get_role_in_org(
            session, role_id=changes["role_id"], org_id=org_id
        )
        if membership.role_id != changes["role_id"]:
            role_changed = True
        membership.role_id = changes["role_id"]

    await session.commit()
    await session.refresh(user)

    after = {
        "full_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "phone": profile.mobile_no,
        "role_id": str(membership.role_id),
    }
    await log_entity_change(
        action="users.updated",
        entity_type="user",
        entity_id=user_id,
        before=before,
        after=after,
    )

    # Emit a separate event when role assignment changed so an
    # auditor can query role-assignment history without parsing every
    # `users.updated` diff.
    if role_changed and new_role is not None:
        before_role_name = (
            await session.execute(
                select(Role.name).where(Role.id == before_role_id)
            )
        ).scalar_one_or_none()
        await audit.log(
            "roles.assigned_to_user",
            entity_type="user",
            entity_id=user_id,
            before={
                "role_id": str(before_role_id),
                "role_name": before_role_name,
            },
            after={
                "role_id": str(new_role.id),
                "role_name": new_role.name,
            },
        )
    return user


async def set_user_status(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    is_active: bool,
) -> User:
    """Activate or deactivate a user.

    Deactivating revokes every non-revoked `auth_sessions` row for the
    user so existing JWTs can no longer authenticate.

    Deactivation is refused under two conditions:
      - the target user is the workspace Owner (403) — they must
        transfer ownership first;
      - the target still has open records (409) — the caller must
        run `POST /users/{id}/transfer-records` to a new owner first.
    """
    user, membership = await data_access.require_membership(
        session,
        user_uuid=user_id,
        org_id=org_id,
        on_missing=status.HTTP_404_NOT_FOUND,
    )

    if not is_active:
        # Owner guard first — the most authoritative refusal.
        await data_access.assert_not_owner_role(
            session, user_uuid=user_id, org_id=org_id
        )
        counts = await data_access.compute_open_records_counts(
            session, user_uuid=user_id, org_id=org_id
        )
        if counts["total"] > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "user has open records",
                    "open_records": counts,
                    "hint": (
                        "POST /users/{id}/transfer-records to a new owner "
                        "before deactivating."
                    ),
                },
            )

    user.is_active = is_active
    membership.is_active = is_active

    if not is_active:
        # Revoke open sessions so existing JWTs stop working.
        now = datetime.now(timezone.utc)
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    await session.commit()
    await session.refresh(user)

    await audit.log(
        "users.activated" if is_active else "users.deactivated",
        entity_type="user",
        entity_id=user_id,
    )
    return user


# --- self-service (2.5.5) ----------------------------------------------


async def update_self(
    session: AsyncSession,
    *,
    user: User,
    payload: MeUpdate,
) -> User:
    """Apply a self-edit to the calling user's `tbl_user_info` row.

    Email is intentionally NOT in `MeUpdate` — changing email means
    inviting a new account. Only the profile fields the user can
    self-manage are honoured here.
    """
    profile = await data_access.get_user_info(session, user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="profile row missing — data inconsistency",
        )

    changes = payload.model_dump(exclude_unset=True)
    before = {
        "full_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "phone": profile.mobile_no,
    }

    if "full_name" in changes and changes["full_name"] is not None:
        first, last = _split_full_name(changes["full_name"])
        profile.first_name = first
        profile.last_name = last
    if "phone" in changes:
        profile.mobile_no = changes["phone"]

    await session.commit()
    await session.refresh(user)

    after = {
        "full_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "phone": profile.mobile_no,
    }
    await audit.log(
        "users.self_updated",
        entity_type="user",
        entity_id=user.legacy_uuid,
        before=before,
        after=after,
    )
    return user


async def change_password(
    session: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    sign_out_others: bool,
    current_token_id: uuid.UUID | None,
) -> None:
    """Verify current → hash + persist new. Optionally revoke other sessions.

    `current_token_id` is the JWT's `token_id` claim of the request
    invoking this — used to spare the caller's own session when
    `sign_out_others=true` (otherwise the user would be logged out of
    the tab they just used to change their password).
    """
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current password is incorrect",
        )
    if current_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new password must differ from the current one",
        )

    # tbl_user_login.password is mapped as `password` on the layered
    # User model (the `password_hash` attribute is a read-only @property
    # alias). Write through the bigint table-level update.
    new_hash = hash_password(new_password)
    await session.execute(
        update(User.__table__)
        .where(User.__table__.c.id == user.id)
        .values(password=new_hash)
    )

    if sign_out_others:
        now = datetime.now(timezone.utc)
        stmt = (
            update(AuthSession)
            .where(
                AuthSession.user_id == user.legacy_uuid,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        if current_token_id is not None:
            stmt = stmt.where(AuthSession.id != current_token_id)
        await session.execute(stmt)

    await session.commit()

    await audit.log(
        "auth.password.changed",
        entity_type="user",
        entity_id=user.legacy_uuid,
        after={"signed_out_others": sign_out_others},
    )
