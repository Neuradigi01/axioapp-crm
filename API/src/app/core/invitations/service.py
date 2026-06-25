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
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.tenants import data_access as tenants_da
from src.app.core.users import data_access as users_da
from src.app.core.auth.models import AuthSession
from src.app.core.auth.tokens import ACCESS_TOKEN_TTL, encode_token
from src.app.core.invitations import data_access as _da
from src.app.core.invitations.models import Invitation
from src.app.core.invitations.schemas import (
    InvitationAccept,
    InvitationCreate,
)
from src.app.core.users.models import OrganizationMember, UserInfo
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
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[Invitation, str]:
    """Issue an invitation. Returns (row, raw_accept_link)."""
    role = await users_da.get_role_in_org(
        session, role_id=payload.role_id, org_id=org_id
    )

    existing_member_id = await _da.find_user_member_id_by_email(
        session, payload.email
    )
    if existing_member_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"email {payload.email} is already in use by another user"
            ),
        )

    now = datetime.now(timezone.utc)
    pending = await _da.find_pending_invitation_for_email(
        session, org_id=org_id, email=payload.email, now=now
    )
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
    _da.insert_invitation(session, invitation)
    await session.commit()
    await session.refresh(invitation)

    accept_link = (
        f"{frontend_url.rstrip('/')}/accounts/accept-invite?token={raw_token}"
    )

    org = await tenants_da.get_organization_by_id(session, org_id)
    assert org is not None  # caller validated org_id upstream

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
            "role_name": role.name,
            "invited_by_user_id": str(invited_by),
            "expires_at": invitation.expires_at.isoformat(),
        },
        ip=ip,
        ua=ua,
    )
    return invitation, accept_link


async def list_pending(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[Invitation]:
    """Pending (un-accepted, un-expired) invitations for `org_id`."""
    return await _da.list_pending_invitations(
        session, org_id=org_id, now=datetime.now(timezone.utc)
    )


async def revoke_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    org_id: uuid.UUID,
    revoked_by: uuid.UUID | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Revoke = set expires_at to now. The row stays for audit."""
    inv = await _da.get_invitation_in_org(
        session, invitation_id=invitation_id, org_id=org_id
    )
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
        after={
            "revoked_by_user_id": str(revoked_by) if revoked_by else None,
        },
        ip=ip,
        ua=ua,
    )


async def lookup_invitation(
    session: AsyncSession, *, raw_token: str
) -> dict:
    """Unauthenticated. Validates the raw token; raises 404/410 otherwise."""
    inv = await _da.get_invitation_by_token_hash(
        session, _hash_token(raw_token)
    )
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

    role = await _da.get_role_by_id(session, inv.role_id)
    assert role is not None  # invitation FK guarantees role exists
    org = await tenants_da.get_organization_by_id(session, inv.org_id)
    assert org is not None  # invitation FK guarantees org exists

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
    inv = await _da.get_invitation_by_token_hash(
        session, _hash_token(payload.token)
    )
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
    existing_user = await _da.find_user_member_id_by_email(
        session, inv.email
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "email already belongs to a user — ask an admin to "
                "reactivate them instead"
            ),
        )

    new_uuid = uuid.uuid4()
    inserted_id = await _da.insert_user_login_returning_id(
        session,
        legacy_uuid=new_uuid,
        user_id="usr_" + new_uuid.hex,
        password_hash=hash_password(payload.password),
        is_active=True,
        two_factor_enabled=False,
    )

    profile = UserInfo(
        member_id=inserted_id,
        first_name=payload.first_name,
        last_name=payload.last_name or "",
        email=inv.email,
        mobile_no=payload.phone,
        is_email_verified=True,  # link-clicker proves they have the address
        is_mobile_verified=False,
    )
    _da.insert_user_info(session, profile)

    membership = OrganizationMember(
        organization_id=inv.org_id,
        user_member_id=inserted_id,
        role_id=inv.role_id,
        status="active",
        is_active=True,
        is_demo=False,
    )
    _da.insert_organization_member(session, membership)

    inv.accepted_at = datetime.now(timezone.utc)

    # Auto-login: mint a JWT + persist the AuthSession so the
    # accept page can drop the recipient straight into /user/dashboard.
    token_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_TTL
    _da.insert_auth_session(
        session,
        AuthSession(
            id=token_id,
            org_id=inv.org_id,
            user_id=new_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        ),
    )

    await session.commit()

    encoded, exp = encode_token(
        user_id=new_uuid,
        org_id=inv.org_id,
        token_id=token_id,
        now=now,
    )

    role_name = await _da.get_role_name_by_id(session, inv.role_id)

    await audit.log(
        "invitations.accepted",
        entity_type="invitation",
        entity_id=inv.id,
        org_id=inv.org_id,
        user_id=new_uuid,
        after={
            "email": inv.email,
            "role_id": str(inv.role_id),
            "role_name": role_name,
            "accepted_by_user_id": str(new_uuid),
        },
        ip=ip,
        ua=ua,
    )

    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_at": exp,
    }
