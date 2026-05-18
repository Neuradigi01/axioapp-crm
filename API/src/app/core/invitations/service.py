"""Invitations service — issue / list / revoke / lookup / accept.

Token lifecycle:

  1. `create_invitation` mints a 32-byte urandom token, SHA-256 hashes
     it for storage, and emails the raw token in an accept link. The
     row carries `expires_at = now + 7d`.
  2. `lookup_invitation` (unauthenticated) verifies a raw token, returns
     just the human-readable bits (`email`, `role_name`, `org_name`)
     so the accept page can render "Hi Sarah, you're invited to ...".
  3. `accept_invitation` (unauthenticated) re-validates the token,
     inserts rows into `tbl_user_login` + `tbl_user_info` +
     `tbl_organization_members`, stamps `accepted_at`, and returns a
     JWT — the recipient is auto-logged-in into their freshly-created
     account.
  4. `revoke_invitation` bumps `expires_at` to now so lookup 410s on
     the (still-stored, for audit) row.

We use SHA-256 instead of bcrypt because the raw token is already 256
bits of entropy; bcrypt's per-row salt would make WHERE-clause lookup
impossible without iterating every row.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.models import AuthSession
from src.app.core.auth.tokens import ACCESS_TOKEN_TTL, encode_token
from src.app.core.invitations.models import Invitation
from src.app.core.invitations.schemas import (
    InvitationAccept,
    InvitationCreate,
)
from src.app.core.permissions.models import Role
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.email import Email, get_email_backend
from src.app.shared.security.password import hash_password


INVITATION_TTL = timedelta(days=7)


def _hash_token(raw: str) -> str:
    """SHA-256 hex of the raw token — used for indexed lookup."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def create_invitation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    invited_by: uuid.UUID,
    payload: InvitationCreate,
    frontend_url: str,
) -> tuple[Invitation, str]:
    """Issue an invitation. Returns (row, raw_accept_link)."""
    role = (
        await session.execute(
            select(Role).where(
                Role.id == payload.role_id, Role.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role_id {payload.role_id} not found in this org",
        )

    existing_user = (
        await session.execute(
            select(UserInfo.member_id).where(UserInfo.email == payload.email)
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"email {payload.email} is already in use by another user"
            ),
        )

    now = datetime.now(timezone.utc)
    pending = (
        await session.execute(
            select(Invitation.id).where(
                Invitation.org_id == org_id,
                Invitation.email == payload.email,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"pending invitation already exists for {payload.email}",
        )

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        org_id=org_id,
        email=payload.email,
        role_id=payload.role_id,
        invited_by=invited_by,
        token_hash=_hash_token(raw_token),
        expires_at=now + INVITATION_TTL,
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)

    accept_link = (
        f"{frontend_url.rstrip('/')}/accounts/accept-invite?token={raw_token}"
    )

    org = (
        await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
    ).scalar_one()

    body = (
        f"You've been invited to join {org.name} ({org.slug}) "
        f"as a {role.name}.\n\n"
        f"Click the link below to set your password and access your account:\n\n"
        f"  {accept_link}\n\n"
        f"This link expires in 7 days. If you didn't expect this email, "
        f"you can safely ignore it."
    )
    await get_email_backend().send(
        Email(
            to=payload.email,
            subject=f"You're invited to {org.name}",
            body_text=body,
        )
    )

    await audit.log(
        "invitations.sent",
        entity_type="invitation",
        entity_id=invitation.id,
        after={
            "email": payload.email,
            "role_id": str(payload.role_id),
        },
    )
    return invitation, accept_link


async def list_pending(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[Invitation]:
    """Pending (un-accepted, un-expired) invitations for `org_id`."""
    result = await session.execute(
        select(Invitation)
        .where(
            Invitation.org_id == org_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(timezone.utc),
        )
        .order_by(Invitation.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Revoke = set expires_at to now. The row stays for audit."""
    inv = (
        await session.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"invitation {invitation_id} not found",
        )
    if inv.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invitation already accepted",
        )

    inv.expires_at = datetime.now(timezone.utc)
    await session.commit()

    await audit.log(
        "invitations.revoked",
        entity_type="invitation",
        entity_id=inv.id,
        before={"email": inv.email},
    )


async def lookup_invitation(
    session: AsyncSession, *, raw_token: str
) -> dict:
    """Unauthenticated. Validates the raw token; raises 404/410 otherwise."""
    inv = (
        await session.execute(
            select(Invitation).where(
                Invitation.token_hash == _hash_token(raw_token)
            )
        )
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found or already accepted",
        )
    if inv.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="invitation expired",
        )

    role = (
        await session.execute(
            select(Role).where(Role.id == inv.role_id)
        )
    ).scalar_one()
    org = (
        await session.execute(
            select(Organization).where(Organization.id == inv.org_id)
        )
    ).scalar_one()

    return {
        "email": inv.email,
        "role_name": role.name,
        "org_name": org.name,
        "org_slug": org.slug,
    }


async def accept_invitation(
    session: AsyncSession,
    *,
    payload: InvitationAccept,
    ip: str | None = None,
    ua: str | None = None,
) -> dict:
    """Redeem invitation → create user in 3 tables → issue JWT.

    Returns the `LoginResponse`-shaped dict so the caller can hand it
    straight back to the client.
    """
    inv = (
        await session.execute(
            select(Invitation).where(
                Invitation.token_hash == _hash_token(payload.token)
            )
        )
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found or already accepted",
        )
    if inv.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="invitation expired",
        )

    # Email may have been claimed by a separate signup (e.g. an admin
    # ran POST /users for the same address) between issue and accept —
    # surface clearly rather than blowing up on a UNIQUE violation.
    existing_user = (
        await session.execute(
            select(UserInfo.member_id).where(UserInfo.email == inv.email)
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "email already belongs to a user — ask an admin to "
                "reactivate them instead"
            ),
        )

    new_uuid = uuid.uuid4()
    inserted_id = (
        await session.execute(
            pg_insert(User.__table__)
            .values(
                legacy_uuid=new_uuid,
                user_id="usr_" + new_uuid.hex,
                password=hash_password(payload.password),
                is_active=True,
                two_factor_enabled=False,
            )
            .returning(User.__table__.c.id)
        )
    ).scalar_one()

    profile = UserInfo(
        member_id=inserted_id,
        first_name=payload.first_name,
        last_name=payload.last_name or "",
        email=inv.email,
        mobile_no=payload.phone,
        is_email_verified=True,  # link-clicker proves they have the address
        is_mobile_verified=False,
    )
    session.add(profile)

    membership = OrganizationMember(
        organization_id=inv.org_id,
        user_member_id=inserted_id,
        role_id=inv.role_id,
        status="active",
        is_active=True,
        is_demo=False,
    )
    session.add(membership)

    inv.accepted_at = datetime.now(timezone.utc)

    # Auto-login: mint a JWT + persist the AuthSession so the
    # accept page can drop the recipient straight into /user/dashboard.
    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL
    session.add(
        AuthSession(
            id=token_id,
            org_id=inv.org_id,
            user_id=new_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )

    await session.commit()

    encoded, exp = encode_token(
        user_id=new_uuid,
        org_id=inv.org_id,
        token_id=token_id,
        now=now,
    )

    await audit.log(
        "invitations.accepted",
        entity_type="invitation",
        entity_id=inv.id,
        org_id=inv.org_id,
        user_id=new_uuid,
        after={"email": inv.email},
    )

    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_at": exp,
    }
