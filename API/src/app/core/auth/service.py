"""Auth service: login / refresh / logout.

Each function takes an `AsyncSession` so the router can inject the
test DB via `Depends(get_db)`. No mutable module state.

`org_slug` resolves the tenant for login (default decision noted in
the step file). All queries inside the login flow scope by `org_id`
explicitly — the auto-tenant ORM filter is a no-op here because the
request enters with no tenant context yet (no JWT decoded).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.models import AuthSession
from src.app.core.auth.schemas import (
    LoginResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
)
from src.app.core.auth.tokens import ACCESS_TOKEN_TTL, TokenClaims, encode_token
from src.app.core.permissions import role_templates
from src.app.core.tenants.models import Organization
from src.app.core.tenants.service import create_organization
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password, verify_password


async def _get_org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def _resolve_org_for_email(
    db: AsyncSession, email: str
) -> Organization | None:
    """Find the org by walking email → active membership → org.

    Used when login is called without `org_slug` (the email-only flow).
    Returns None when the email isn't known OR has no active membership —
    the caller treats both as "invalid credentials" to avoid leaking
    which case it was.
    """
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(UserInfo, UserInfo.member_id == OrganizationMember.user_member_id)
        .where(
            UserInfo.email == email,
            OrganizationMember.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _get_user_by_email_in_org(
    db: AsyncSession, org_id: uuid.UUID, email: str
) -> User | None:
    # Three-table lookup after DR.7: `tbl_user_info` carries the email,
    # `tbl_organization_members` carries the org membership + active
    # flag, `tbl_user_login` carries auth state. We require the
    # membership to be `is_active=true` so a deactivated user is
    # filtered out even if their auth row is still active.
    result = await db.execute(
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .where(
            UserInfo.email == email,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    org_slug: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> LoginResponse:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )

    if org_slug:
        org = await _get_org_by_slug(db, org_slug)
    else:
        org = await _resolve_org_for_email(db, email)
    if org is None:
        # No tenant known → can't attribute to a row, intentionally skip audit.
        raise invalid

    user = await _get_user_by_email_in_org(db, org.id, email)
    if user is None or not user.is_active:
        await audit.log(
            "auth.login.failure",
            org_id=org.id,
            user_id=None,
            before={"email": email, "reason": "unknown_or_inactive_user"},
            ip=ip,
            ua=ua,
        )
        raise invalid
    if not verify_password(password, user.password_hash):
        await audit.log(
            "auth.login.failure",
            org_id=org.id,
            user_id=None,
            before={"email": email, "reason": "bad_password"},
            ip=ip,
            ua=ua,
        )
        raise invalid

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL

    # `user.id` is the bigint storage PK of `tbl_user_login` (DR.6.3).
    # Every UUID-typed `user_id` FK (AuthSession.user_id → users.id,
    # audit_logs.user_id, JWT `sub`) references the user by the UUID
    # identity preserved in `user.legacy_uuid`.
    user_uuid = user.legacy_uuid

    db.add(
        AuthSession(
            id=token_id,
            org_id=org.id,
            user_id=user_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )
    await db.commit()

    await audit.log(
        "auth.login.success",
        org_id=org.id,
        user_id=user_uuid,
        after={"token_id": str(token_id)},
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user_uuid, org_id=org.id, token_id=token_id, now=now
    )
    return LoginResponse(access_token=encoded, expires_at=exp)


async def refresh(db: AsyncSession, claims: TokenClaims) -> RefreshResponse:
    """Revoke the current session and issue a fresh JWT with a new token_id."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or revoked token",
    )

    session = (
        await db.execute(select(AuthSession).where(AuthSession.id == claims.token_id))
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise invalid

    now = datetime.now(timezone.utc)
    if session.expires_at <= now:
        raise invalid

    # Revoke old, issue new.
    session.revoked_at = now
    new_token_id = uuid.uuid4()
    new_expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=new_token_id,
            org_id=session.org_id,
            user_id=session.user_id,
            expires_at=new_expires_at,
            ip=session.ip,
            ua=session.ua,
        )
    )
    await db.commit()

    encoded, exp = encode_token(
        user_id=session.user_id,
        org_id=session.org_id,
        token_id=new_token_id,
        now=now,
    )
    return RefreshResponse(access_token=encoded, expires_at=exp)


async def logout(db: AsyncSession, token_id: uuid.UUID) -> None:
    """Idempotent — sets `revoked_at` to now if the row exists and isn't already revoked."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == token_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()


async def _email_taken(db: AsyncSession, email: str) -> bool:
    result = await db.execute(select(UserInfo.id).where(UserInfo.email == email))
    return result.scalar_one_or_none() is not None


async def register_with_new_org(
    db: AsyncSession,
    *,
    req: RegisterRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> RegisterResponse:
    """Atomic signup: org + Owner role-template seed + user + membership.

    Either every insert lands or none do. On success returns a JWT for
    the newly-created Owner, ready to be carried by the frontend into
    `/user/dashboard`.
    """
    if await _email_taken(db, req.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    workspace_name = (req.organization_name or "").strip() or (
        f"{req.first_name.strip()}'s Workspace"
    )

    org = await create_organization(
        db, name=workspace_name, created_via="normal_signup"
    )

    # Role-template install is tenant-scoped via the auto-filter; set
    # the request context to the new org so the installer's reads of
    # `roles` see (and only see) this org's rows.
    token = set_context(RequestContext(org_id=org.id))
    try:
        installed = await role_templates.install(db, org_id=org.id)
    except role_templates.UnknownPermissionKey as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"role template install failed: {exc}",
        )
    finally:
        reset_context(token)

    owner_role = installed.get("owner")
    if owner_role is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="role template install did not produce an Owner role",
        )

    # `User` (layered mapper) hides legacy `user_id` / 2FA columns. Bypass
    # the exclusion by inserting via `pg_insert(User)` — same trick the
    # seed scripts use — then fetch the bigint id by `legacy_uuid`.
    user_uuid = uuid.uuid4()
    await db.execute(
        pg_insert(User).values(
            {
                "legacy_uuid": user_uuid,
                "user_id": f"usr_{user_uuid.hex}",
                "password": hash_password(req.password),
                "is_active": True,
                "two_factor_enabled": False,
            }
        )
    )
    bigint_id = (
        await db.execute(
            select(User.id).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one()

    db.add(
        UserInfo(
            member_id=bigint_id,
            first_name=req.first_name.strip(),
            last_name=req.last_name.strip(),
            email=req.email,
            mobile_no=req.phone,
            is_email_verified=False,
            is_mobile_verified=False,
        )
    )
    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_member_id=bigint_id,
            role_id=owner_role.id,
            status="active",
            is_active=True,
            is_demo=False,
        )
    )

    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL
    db.add(
        AuthSession(
            id=token_id,
            org_id=org.id,
            user_id=user_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )

    await db.commit()

    await audit.log(
        "auth.signup",
        org_id=org.id,
        user_id=user_uuid,
        after={
            "email": req.email,
            "organization_name": org.name,
            "organization_slug": org.slug,
            "role": owner_role.name,
        },
        ip=ip,
        ua=ua,
    )

    encoded, exp = encode_token(
        user_id=user_uuid, org_id=org.id, token_id=token_id, now=now
    )
    return RegisterResponse(
        access_token=encoded,
        expires_at=exp,
        organization_id=org.id,
        organization_slug=org.slug,
        role_name=owner_role.name,
    )
