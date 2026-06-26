"""Data-access layer for the auth module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Liveness checks (`revoked_at is None`, `expires_at > now`) are kept on
the caller side because each authentication path interprets a
revoked / expired session differently — middleware raises 401, the WS
upgrade closes with policy-violation, the logout endpoint returns
204 no-op. The DAL just returns the row.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.models import AuthSession
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, UserInfo


async def get_auth_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> AuthSession | None:
    """Resolve an auth-session row by id.

    `user_id` adds a second predicate so a caller can verify the
    session belongs to the user it's acting on — used by
    `POST /auth/sessions/{id}/revoke` to refuse cross-user revokes
    without leaking the existence of someone else's session.
    """
    stmt = select(AuthSession).where(AuthSession.id == session_id)
    if user_id is not None:
        stmt = stmt.where(AuthSession.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def add_auth_session(
    session: AsyncSession, row: AuthSession
) -> AuthSession:
    """Stage a new `auth_sessions` row in the unit-of-work."""
    session.add(row)
    return row


async def revoke_auth_session_by_id(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    now: datetime,
) -> None:
    """Idempotent revoke — sets `revoked_at` only if still NULL."""
    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.id == token_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def list_auth_sessions_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
) -> list[AuthSession]:
    """Most recent auth-session rows for one user (newest first)."""
    result = await session.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user_id)
        .order_by(AuthSession.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_organization_for_email(
    session: AsyncSession, email: str
) -> Organization | None:
    """Walk email → active membership → org.

    Used by the email-only login path: when no `org_slug` is supplied,
    we infer the tenant from the first active membership the email has.
    Returns None when no active membership exists.
    """
    result = await session.execute(
        select(Organization)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .join(
            UserInfo,
            UserInfo.member_id == OrganizationMember.user_member_id,
        )
        .where(
            UserInfo.email == email,
            OrganizationMember.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_user_two_factor_flags(
    session: AsyncSession, *, member_id: int
) -> tuple[bool, str | None]:
    """Read `(enabled, method)` from `tbl_user_login` for the given user.

    Goes through the legacy `UserLogin` mapping because the layered
    `User` mapper excludes the `two_factor_*` columns. `member_id` is
    `User.id` (the `tbl_user_login.id` bigint PK).
    """
    from src.models.user import UserLogin

    row = (
        await session.execute(
            select(
                UserLogin.two_factor_enabled,
                UserLogin.two_factor_method,
            ).where(UserLogin.id == member_id)
        )
    ).one_or_none()
    if row is None:
        return False, None
    return bool(row[0]), row[1]


__all__ = [
    "add_auth_session",
    "get_auth_session",
    "get_organization_for_email",
    "get_user_two_factor_flags",
    "list_auth_sessions_for_user",
    "revoke_auth_session_by_id",
]
