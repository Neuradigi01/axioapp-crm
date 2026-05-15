"""Service layer for the staff-portal auth surface.

Four concerns:

1. `list_pickable_users(org_slug)` — public-within-the-org login picker.
   Returns minimal `(id, full_name, avatar)` rows for users in the
   resolved org whose `staff_profile.employment_status='active'`. No
   email, phone, or role secrets leak.
2. `login(org_slug, user_id, pin)` — validates the org, validates the
   user belongs to that org and has an active staff profile, then
   compares `pin` against the last 4 digits of `users.phone`. On
   success mints a `scope="staff"` JWT and persists a `staff_sessions`
   row for revocation.
3. Rate limit — 5 attempts per minute per `(org_id, user_id)`. We keep
   the counter in-process (module-level dict). Single-worker dev/test
   suffices; a multi-worker prod deploy will fold this into Redis but
   the public API stays the same.
4. Audit — every login attempt fires `staff_portal.login_*` so HR has
   a complete record (success and failure both).
"""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.tokens import STAFF_TOKEN_TTL, encode_token
from src.app.core.staff.models import EmploymentStatus, StaffProfile
from src.app.core.staff_portal.models import StaffSession
from src.app.core.staff_portal.schemas import StaffPickerUser
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User, UserInfo


# --- rate limiting ---------------------------------------------------------

_RATE_WINDOW = timedelta(minutes=1)
_RATE_MAX = 5
# (org_id, user_id) -> deque[datetime] of recent attempt timestamps.
_attempts: dict[tuple[uuid.UUID, uuid.UUID], deque[datetime]] = {}


def _prune_attempts(key: tuple[uuid.UUID, uuid.UUID], now: datetime) -> None:
    bucket = _attempts.get(key)
    if not bucket:
        return
    cutoff = now - _RATE_WINDOW
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _record_attempt(key: tuple[uuid.UUID, uuid.UUID], now: datetime) -> None:
    bucket = _attempts.setdefault(key, deque())
    bucket.append(now)


def _is_rate_limited(key: tuple[uuid.UUID, uuid.UUID], now: datetime) -> bool:
    _prune_attempts(key, now)
    bucket = _attempts.get(key)
    return bool(bucket and len(bucket) >= _RATE_MAX)


def reset_rate_limit() -> None:
    """Test-only — clear the in-memory attempt counter between cases."""
    _attempts.clear()


# --- queries ---------------------------------------------------------------


async def _resolve_org(session: AsyncSession, org_slug: str) -> Organization:
    org = (
        await session.execute(
            select(Organization).where(Organization.slug == org_slug)
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )
    return org


async def list_pickable_users(
    session: AsyncSession, *, org_slug: str
) -> list[StaffPickerUser]:
    """Active staff for the login picker. No PII beyond name."""
    org = await _resolve_org(session, org_slug)

    # users with an active staff profile, ordered by name. Users
    # without a staff_profile row are intentionally excluded — they
    # can't clock in until HR sets them up.
    stmt = (
        select(
            User.legacy_uuid.label("legacy_uuid"),
            UserInfo.first_name,
            UserInfo.last_name,
        )
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .join(StaffProfile, StaffProfile.user_id == User.legacy_uuid)
        .where(OrganizationMember.organization_id == org.id)
        .where(OrganizationMember.is_active.is_(True))
        .where(User.is_active.is_(True))
        .where(StaffProfile.employment_status == EmploymentStatus.active)
        .order_by(UserInfo.first_name.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        StaffPickerUser(
            id=row.legacy_uuid,
            full_name=" ".join(
                p for p in (row.first_name, row.last_name) if p
            ).strip(),
            avatar=None,
        )
        for row in rows
    ]


def _pin_for_phone(phone: str | None) -> str | None:
    """Return the last 4 digits of a phone number, or None if not derivable."""
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 4:
        return None
    return digits[-4:]


async def login(
    session: AsyncSession,
    *,
    org_slug: str,
    user_id: uuid.UUID,
    pin: str,
    ip: str | None = None,
    ua: str | None = None,
) -> dict[str, Any]:
    """Validate PIN → mint staff JWT → persist `staff_sessions` row."""
    org = await _resolve_org(session, org_slug)

    user = (
        await session.execute(
            select(User)
            .join(
                OrganizationMember,
                OrganizationMember.user_member_id == User.id,
            )
            .where(User.legacy_uuid == user_id)
            .where(OrganizationMember.organization_id == org.id)
            .where(OrganizationMember.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        await audit.log(
            "staff_portal.login_failed",
            entity_type="user",
            entity_id=user_id,
            org_id=org.id,
            ip=ip,
            ua=ua,
            after={"reason": "user_not_found_or_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    profile = (
        await session.execute(
            select(StaffProfile).where(StaffProfile.user_id == user.legacy_uuid)
        )
    ).scalar_one_or_none()
    if profile is None or profile.employment_status != EmploymentStatus.active:
        await audit.log(
            "staff_portal.login_failed",
            entity_type="user",
            entity_id=user.legacy_uuid,
            org_id=org.id,
            user_id=user.legacy_uuid,
            ip=ip,
            ua=ua,
            after={"reason": "profile_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    now = datetime.now(timezone.utc)
    rate_key = (org.id, user.legacy_uuid)
    if _is_rate_limited(rate_key, now):
        await audit.log(
            "staff_portal.login_rate_limited",
            entity_type="user",
            entity_id=user.legacy_uuid,
            org_id=org.id,
            user_id=user.legacy_uuid,
            ip=ip,
            ua=ua,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts, try again later",
        )

    expected = _pin_for_phone(user.phone)
    if expected is None or pin != expected:
        _record_attempt(rate_key, now)
        await audit.log(
            "staff_portal.login_failed",
            entity_type="user",
            entity_id=user.legacy_uuid,
            org_id=org.id,
            user_id=user.legacy_uuid,
            ip=ip,
            ua=ua,
            after={"reason": "bad_pin"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    # Success — mint token + persist session.
    token_id = uuid.uuid4()
    encoded, expires_at = encode_token(
        user_id=user.legacy_uuid,
        org_id=org.id,
        token_id=token_id,
        ttl=STAFF_TOKEN_TTL,
        scope="staff",
    )
    session.add(
        StaffSession(
            id=token_id,
            org_id=org.id,
            user_id=user.legacy_uuid,
            expires_at=expires_at,
            ip=ip,
            ua=ua,
        )
    )
    await session.commit()

    # Clear the failure window so a fresh login doesn't penalise the
    # next attempt window for this user.
    _attempts.pop(rate_key, None)

    await audit.log(
        "staff_portal.login_succeeded",
        entity_type="user",
        entity_id=user.legacy_uuid,
        org_id=org.id,
        user_id=user.legacy_uuid,
        ip=ip,
        ua=ua,
    )

    return {
        "staff_token": encoded,
        "expires_at": expires_at,
        "user_id": user.legacy_uuid,
        "org_id": org.id,
    }


__all__ = [
    "list_pickable_users",
    "login",
    "reset_rate_limit",
]
