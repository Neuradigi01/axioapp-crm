"""Data-access layer for the invitations module.

Pure query helpers — no transactions, no audit, no email send, no
hashing. Leaf module; never imports a ``service.py``.

Operations cover the invitation lifecycle plus the cross-module
writes the ``accept_invitation`` flow performs (creating a User +
UserInfo + OrganizationMember + AuthSession in one transaction):

  * Invitations (``tbl_invitations``)
      get_invitation_in_org, get_invitation_by_token_hash,
      find_pending_invitation_for_email,
      list_pending_invitations, insert_invitation
  * Cross-module reads
      find_user_member_id_by_email — User-table existence check
        scoped through UserInfo
      get_role_name_by_id — best-effort label for the audit row
  * Cross-module writes for the accept flow
      insert_user_login_returning_id — pg_insert + RETURNING for
        the new User row
      insert_user_info, insert_organization_member,
      insert_auth_session — caller commits

The cross-module write helpers are tightly coupled to the accept
flow's exact column set; they trade architectural purity (writes
into other modules' tables ought to go through those modules'
services) for keeping the accept transaction atomic in one place.
A future polish step can route these through users + auth services
once those expose ``insert_in_session`` style helpers.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.models import AuthSession
from src.app.core.invitations.models import Invitation
from src.app.core.permissions.models import Role
from src.app.core.users.models import OrganizationMember, User, UserInfo


# --- Invitation reads ---------------------------------------------------


async def get_invitation_in_org(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    org_id: uuid.UUID,
) -> Optional[Invitation]:
    """Single invitation row scoped to one org — used by revoke so
    a caller can't act on a foreign-org invitation even if they
    guess the UUID."""
    return (
        await session.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.org_id == org_id,
            )
        )
    ).scalar_one_or_none()


async def get_invitation_by_token_hash(
    session: AsyncSession, token_hash: str
) -> Optional[Invitation]:
    """Resolve an invitation by the SHA-256 hash of its raw token.
    ``None`` on miss — caller raises 404."""
    return (
        await session.execute(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
    ).scalar_one_or_none()


async def find_pending_invitation_for_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    now: datetime,
) -> Optional[uuid.UUID]:
    """Return the id of an active (un-accepted, un-expired) invitation
    for ``email`` in ``org_id``, if one exists. Used by create to
    refuse double-invitations."""
    return (
        await session.execute(
            select(Invitation.id).where(
                Invitation.org_id == org_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
    ).scalar_one_or_none()


async def list_pending_invitations(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    now: datetime,
) -> list[Invitation]:
    """All pending invitations for ``org_id`` (un-accepted,
    un-expired), newest first."""
    result = await session.execute(
        select(Invitation)
        .where(
            Invitation.org_id == org_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > now,
        )
        .order_by(Invitation.created_at.desc())
    )
    return list(result.scalars().all())


def insert_invitation(
    session: AsyncSession, invitation: Invitation
) -> None:
    """Register an already-constructed Invitation for INSERT."""
    session.add(invitation)


# --- Cross-module reads -------------------------------------------------


async def find_user_member_id_by_email(
    session: AsyncSession, email: str
) -> Optional[int]:
    """Resolve a user's bigint id by their UserInfo.email — used by
    both create (refuse duplicate-email invite) and accept (defensive
    second check between issue + accept).

    Cross-module read against ``tbl_user_info``; kept here because
    the projection is invitation-specific (just the int id). The
    canonical user lookups stay in ``core/users/data_access.py``.
    """
    return (
        await session.execute(
            select(UserInfo.member_id).where(UserInfo.email == email)
        )
    ).scalar_one_or_none()


async def get_role_name_by_id(
    session: AsyncSession, role_id: uuid.UUID
) -> Optional[str]:
    """Best-effort role-name lookup for the audit row. Returns
    ``None`` if the role row vanished between the lookup and the
    audit emit (vanishingly unlikely; invite FKs use RESTRICT)."""
    return (
        await session.execute(
            select(Role.name).where(Role.id == role_id)
        )
    ).scalar_one_or_none()


async def get_role_by_id(
    session: AsyncSession, role_id: uuid.UUID
) -> Optional[Role]:
    """Full Role row by id — used by the ``lookup_invitation`` flow
    to surface the role name on the accept page."""
    return (
        await session.execute(
            select(Role).where(Role.id == role_id)
        )
    ).scalar_one_or_none()


# --- Cross-module writes (accept flow) ----------------------------------


async def insert_user_login_returning_id(
    session: AsyncSession,
    *,
    legacy_uuid: uuid.UUID,
    user_id: str,
    password_hash: str,
    is_active: bool = True,
    two_factor_enabled: bool = False,
) -> int:
    """INSERT into ``tbl_user_login`` and RETURN the bigint PK so the
    caller can attach the dependent UserInfo + OrganizationMember
    rows in the same transaction.

    PostgreSQL ``INSERT ... RETURNING`` keeps the round-trip count
    minimal — alternative would be ``flush() + refresh()`` after a
    plain session.add, which costs an extra SELECT.
    """
    result = await session.execute(
        pg_insert(User.__table__)
        .values(
            legacy_uuid=legacy_uuid,
            user_id=user_id,
            password=password_hash,
            is_active=is_active,
            two_factor_enabled=two_factor_enabled,
        )
        .returning(User.__table__.c.id)
    )
    return int(result.scalar_one())


def insert_user_info(
    session: AsyncSession, profile: UserInfo
) -> None:
    """Register an already-constructed UserInfo for INSERT."""
    session.add(profile)


def insert_organization_member(
    session: AsyncSession, member: OrganizationMember
) -> None:
    """Register an already-constructed OrganizationMember for INSERT."""
    session.add(member)


def insert_auth_session(
    session: AsyncSession, auth_session_row: AuthSession
) -> None:
    """Register an already-constructed AuthSession for INSERT."""
    session.add(auth_session_row)


__all__ = [
    "find_pending_invitation_for_email",
    "find_user_member_id_by_email",
    "get_invitation_by_token_hash",
    "get_invitation_in_org",
    "get_role_by_id",
    "get_role_name_by_id",
    "insert_auth_session",
    "insert_invitation",
    "insert_organization_member",
    "insert_user_info",
    "insert_user_login_returning_id",
    "list_pending_invitations",
]
