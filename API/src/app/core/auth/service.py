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
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.models import AuthSession
from src.app.core.auth.schemas import LoginResponse, RefreshResponse
from src.app.core.auth.tokens import ACCESS_TOKEN_TTL, TokenClaims, encode_token
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.security.password import verify_password


async def _get_org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
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
    org_slug: str,
    ip: str | None = None,
    ua: str | None = None,
) -> LoginResponse:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )

    org = await _get_org_by_slug(db, org_slug)
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
