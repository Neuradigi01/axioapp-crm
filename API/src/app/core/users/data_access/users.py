"""User-and-profile lookups against `tbl_user_login` + `tbl_user_info`.

All functions are pure reads — no commits, no audit. Callers that need
transactional behaviour (insert / update / delete) live in
`users.service`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.users.models import OrganizationMember, User, UserInfo


async def get_user_by_uuid(
    session: AsyncSession, user_uuid: uuid.UUID
) -> User | None:
    """Look up a FurnitureCRM user by their UUID identity.

    `User.id` is a bigint storage PK; the UUID that JWT `sub`, audit
    FKs, AuthSession.user_id, etc. carry around lives in
    `User.legacy_uuid`. This helper queries against that column.
    """
    result = await session.execute(
        select(User).where(User.legacy_uuid == user_uuid)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(
    session: AsyncSession,
    email: str,
    *,
    org_id: uuid.UUID | None = None,
    active_only: bool = False,
) -> User | None:
    """Lookup by email. Email lives on `tbl_user_info` (CITEXT, case-insensitive).

    - `org_id=None`        : global lookup (any user with this email).
    - `org_id` set         : scope to users with a membership row in that org.
    - `active_only=True`   : require `User.is_active` AND, when org-scoped,
                             `OrganizationMember.is_active`.

    The 3-table join in the org-scoped path mirrors the auth-service lookup
    that this helper replaces — callers that previously rolled their own
    inline JOIN get the same row back.
    """
    stmt = (
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .where(UserInfo.email == email)
    )
    if org_id is not None:
        stmt = stmt.join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        ).where(OrganizationMember.organization_id == org_id)
        if active_only:
            stmt = stmt.where(OrganizationMember.is_active.is_(True))
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_info(
    session: AsyncSession, member_id: int
) -> UserInfo | None:
    """Profile row lookup by `tbl_user_login.id` (bigint)."""
    result = await session.execute(
        select(UserInfo).where(UserInfo.member_id == member_id)
    )
    return result.scalar_one_or_none()


async def email_exists(session: AsyncSession, email: str) -> bool:
    """True if any `tbl_user_info` row carries this email.

    `tbl_user_info.email` is globally unique, so this is the right
    pre-check for `create_user` to surface a 409 before the insert.
    """
    result = await session.execute(
        select(UserInfo.member_id).where(UserInfo.email == email)
    )
    return result.scalar_one_or_none() is not None
