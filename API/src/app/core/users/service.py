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
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.permissions.models import Role
from src.app.core.users import data_access
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
    """List CRM users, optionally scoped to an org membership."""
    return await data_access.list_users_in_org(session, org_id=org_id, limit=limit, offset=offset)


async def get_user_by_email(
    session: AsyncSession,
    email: str,
    *,
    org_id: uuid.UUID | None = None,
    active_only: bool = False,
) -> User | None:
    """Public lookup-by-email wrapper. Thin pass-through to the DAL so
    other modules' routers (e.g. the 2FA switch-method endpoint) don't
    reach into `users.data_access` directly."""
    return await data_access.get_user_by_email(
        session, email, org_id=org_id, active_only=active_only
    )


async def get_user_by_uuid(session: AsyncSession, user_uuid: uuid.UUID) -> User | None:
    """Public lookup-by-uuid wrapper. Used by other modules
    (appointments, staff) to resolve a user without reaching into
    `users.data_access` directly."""
    return await data_access.get_user_by_uuid(session, user_uuid)


async def email_exists(session: AsyncSession, email: str) -> bool:
    """Public email-exists check. Used by signup paths to surface a
    409 before insert."""
    return await data_access.email_exists(session, email)


async def insert_user_login_row(
    session: AsyncSession,
    *,
    legacy_uuid: uuid.UUID,
    user_handle: str,
    password_hash: str,
) -> int:
    """Public table-level user insert wrapper. Used by the auth
    signup flow which constructs a user as part of org creation."""
    return await data_access.insert_user_login_row(
        session,
        legacy_uuid=legacy_uuid,
        user_handle=user_handle,
        password_hash=password_hash,
    )


def add_user_info(session: AsyncSession, info):
    """Public user_info stage wrapper for signup flows."""
    return data_access.add_user_info(session, info)


def add_organization_member(session: AsyncSession, member):
    """Public membership stage wrapper for signup flows."""
    return data_access.add_organization_member(session, member)


async def get_role_name_by_id(session: AsyncSession, role_id: uuid.UUID) -> str | None:
    """Public role-name lookup wrapper. Used by auth's onboarding
    response to project the role name into the JWT response."""
    return await data_access.get_role_name_by_id(session, role_id)


async def get_role_in_org(session: AsyncSession, *, role_id: uuid.UUID, org_id: uuid.UUID):
    """Validate that `role_id` exists in `org_id`. Raises 422 if not —
    used by user-create / user-update / invitation-accept to gate
    the chosen role assignment before persisting it.

    Business rule (422 vs 404 vs returning None) lives here, not in
    the DAL; DAL just answers "does this row exist".
    """
    role = await data_access.get_role_by_id_in_org(session, role_id=role_id, org_id=org_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role_id {role_id} not found in this org",
        )
    return role


async def require_membership(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
    active_only: bool = False,
    on_missing: int = status.HTTP_404_NOT_FOUND,
    not_found_detail: str | None = None,
    not_member_detail: str | None = None,
):
    """Resolve user-UUID → User → OrganizationMember in this org.

    Raises `HTTPException(status_code=on_missing, ...)` if the user
    doesn't exist or has no matching membership. Returns the
    `(User, OrganizationMember)` pair so callers can keep working with
    both without re-querying.

    `on_missing` controls the response code:
      - 404 (default) : for admin CRUD paths.
      - 422           : validation failure (ownership-transfer target,
                        offboarding target).
      - 403           : authorization failure (caller has no membership).

    Business rule lives here in service; DAL only answers "does this
    row exist".
    """
    user = await data_access.get_user_by_uuid(session, user_uuid)
    if user is None:
        raise HTTPException(
            status_code=on_missing,
            detail=not_found_detail or f"user {user_uuid} not found",
        )
    membership = await data_access.get_membership(
        session,
        user_member_id=user.id,
        org_id=org_id,
        active_only=active_only,
    )
    if membership is None:
        raise HTTPException(
            status_code=on_missing,
            detail=not_member_detail or f"user {user_uuid} is not a member of this org",
        )
    return user, membership


async def assert_not_owner_role(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Refuse Owner deactivation.

    Business rule: the workspace Owner must transfer ownership before
    being deactivated. Raises 403 (not 422) — authorisation-level
    invariant the caller can't bypass regardless of input. Silent on
    user-not-found / not-in-org so the upstream 404 wins.
    """
    user = await data_access.get_user_by_uuid(session, user_uuid)
    if user is None:
        return
    membership = await data_access.get_membership(session, user_member_id=user.id, org_id=org_id)
    if membership is None:
        return
    role = await data_access.get_role_by_id(session, membership.role_id)
    if role is None:
        return
    if role.name == "Owner" and role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("the workspace Owner cannot be deactivated — transfer ownership first"),
        )


async def get_role_by_id_in_org(session: AsyncSession, *, role_id: uuid.UUID, org_id: uuid.UUID):
    """Public role lookup that returns None on miss. Used by
    permissions service for guard-checks where the caller picks
    the HTTP status."""
    return await data_access.get_role_by_id_in_org(session, role_id=role_id, org_id=org_id)


async def count_active_members(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Public active-seats counter. Used by the subscriptions
    service to compute `seats.in_use`."""
    return await data_access.count_active_members(session, org_id)


async def compute_open_records_counts(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, int]:
    """Per-entity open-record counts for the deactivation modal.

    Public service wrapper around the offboarding query helper so
    routers go through the service layer per the layered-architecture
    contract.
    """
    return await data_access.compute_open_records_counts(
        session, user_uuid=user_uuid, org_id=org_id
    )


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
    await get_role_in_org(session, role_id=payload.role_id, org_id=org_id)

    if await data_access.email_exists(session, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"email {payload.email} is already in use",
        )

    # The layered `User` mapper excludes the legacy `user_id` text
    # handle and the `two_factor_*` columns (they live on the legacy
    # `UserLogin` mapper) — but both are NOT NULL on `tbl_user_login`.
    # DAL inserts at the table level, then we load the freshly-inserted
    # row through the layered mapper to get the relationships hydrated.
    new_uuid = uuid.uuid4()
    new_id = await data_access.insert_user_login_row(
        session,
        legacy_uuid=new_uuid,
        user_handle="usr_" + new_uuid.hex,
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    login = await data_access.get_user_by_id(session, new_id)
    assert login is not None  # we just inserted it

    first, last = _split_full_name(payload.full_name)
    data_access.add_user_info(
        session,
        UserInfo(
            member_id=login.id,
            first_name=first,
            last_name=last,
            email=payload.email,
            mobile_no=payload.phone,
            is_email_verified=False,
            is_mobile_verified=False,
        ),
    )
    data_access.add_organization_member(
        session,
        OrganizationMember(
            organization_id=org_id,
            user_member_id=login.id,
            role_id=payload.role_id,
            status="active",
            is_active=True,
            is_demo=False,
        ),
    )

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
    user, membership = await require_membership(
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
        new_role = await get_role_in_org(session, role_id=changes["role_id"], org_id=org_id)
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
        before_role_name = await data_access.get_role_name_by_id(session, before_role_id)
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
    user, membership = await require_membership(
        session,
        user_uuid=user_id,
        org_id=org_id,
        on_missing=status.HTTP_404_NOT_FOUND,
    )

    if not is_active:
        # Owner guard first — the most authoritative refusal.
        await assert_not_owner_role(session, user_uuid=user_id, org_id=org_id)
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
                        "POST /users/{id}/transfer-records to a new owner before deactivating."
                    ),
                },
            )

    user.is_active = is_active
    membership.is_active = is_active

    if not is_active:
        # Revoke open sessions so existing JWTs stop working.
        await data_access.revoke_user_auth_sessions(
            session, user_uuid=user_id, now=datetime.now(UTC)
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
    # alias). DAL writes through the bigint table-level update.
    await data_access.update_user_password(
        session, member_id=user.id, new_hash=hash_password(new_password)
    )

    if sign_out_others:
        await data_access.revoke_user_auth_sessions(
            session,
            user_uuid=user.legacy_uuid,
            now=datetime.now(UTC),
            except_token_id=current_token_id,
        )

    await session.commit()

    await audit.log(
        "auth.password.changed",
        entity_type="user",
        entity_id=user.legacy_uuid,
        after={"signed_out_others": sign_out_others},
    )
