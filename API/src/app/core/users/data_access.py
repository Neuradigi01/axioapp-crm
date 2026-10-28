"""Data-access layer for the users module.

Pure query helpers — no transactions, no audit writes, no commits.
Leaf module; never imports a ``service.py``. That guarantees callers
can ``from src.app.core.users import data_access`` without triggering
a circular import.

Three concerns kept in one file per the project's layered-architecture
spec (manager-locked 2026-06-25):

  * ``tbl_user_login`` + ``tbl_user_info`` lookups
    (``get_user_by_uuid``, ``get_user_by_email``, ``get_user_info``,
     ``email_exists``).
  * ``tbl_organization_members`` + ``tbl_roles`` lookups
    (``get_membership``, ``count_active_members``,
     ``get_role_by_id_in_org``, ``get_role_by_id``, ``get_owner_role``,
     ``get_admin_role``). Raising / business-rule wrappers
     (``require_membership``, ``get_role_in_org``,
     ``assert_not_owner_role``) live in ``users.service`` — DAL is
     pure CRUD.
  * Offboarding open-record queries
    (``list_open_record_ids``, ``compute_open_records_counts``) —
    co-located here because they share the same per-(user, org)
    predicate shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.auth.models import AuthSession
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import Role
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.core.walk_ins.models import WalkIn, WalkInStatus

# Spec's `('waiting','with_staff')` predates the walk-in state-machine
# rewrite — the live enum is browsing / interested / follow_up /
# converted / left, with `converted` and `left` being terminal. "Open"
# walk-ins are anything still in the engaged / in-store flow.
_WALKIN_OPEN_STATUSES = (
    WalkInStatus.browsing,
    WalkInStatus.interested,
    WalkInStatus.follow_up,
)


# --- user + profile lookups ---------------------------------------------


async def get_user_by_uuid(session: AsyncSession, user_uuid: uuid.UUID) -> User | None:
    """Look up a CRM user by their UUID identity.

    `User.id` is a bigint storage PK; the UUID that JWT `sub`, audit
    FKs, AuthSession.user_id, etc. carry around lives in
    `User.legacy_uuid`. This helper queries against that column.
    """
    result = await session.execute(select(User).where(User.legacy_uuid == user_uuid))
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
    stmt = select(User).join(UserInfo, UserInfo.member_id == User.id).where(UserInfo.email == email)
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


async def get_user_info(session: AsyncSession, member_id: int) -> UserInfo | None:
    """Profile row lookup by `tbl_user_login.id` (bigint)."""
    result = await session.execute(select(UserInfo).where(UserInfo.member_id == member_id))
    return result.scalar_one_or_none()


async def email_exists(session: AsyncSession, email: str) -> bool:
    """True if any `tbl_user_info` row carries this email.

    `tbl_user_info.email` is globally unique, so this is the right
    pre-check for `create_user` to surface a 409 before the insert.
    """
    result = await session.execute(select(UserInfo.member_id).where(UserInfo.email == email))
    return result.scalar_one_or_none() is not None


# --- membership lookups -------------------------------------------------


async def get_membership(
    session: AsyncSession,
    *,
    user_member_id: int,
    org_id: uuid.UUID,
    active_only: bool = False,
) -> OrganizationMember | None:
    """Resolve the membership row for one `(user_bigint_id, org_id)` pair.

    `active_only=True` adds `is_active=true` to the predicate — used by
    paths that should treat a deactivated member as "not in the org"
    (e.g. seat-count, ownership-transfer target validation).
    """
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_member_id == user_member_id,
        OrganizationMember.organization_id == org_id,
    )
    if active_only:
        stmt = stmt.where(OrganizationMember.is_active.is_(True))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def count_active_members(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Number of active members in the org — feeds `seats.in_use` on the
    subscription read API.

    Counts `tbl_organization_members` rows with `is_active=True` for the
    given org. Paused / archived memberships do not consume a seat.
    """
    result = await session.execute(
        select(func.count())
        .select_from(OrganizationMember)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


# --- role lookups -------------------------------------------------------


async def get_role_by_id_in_org(
    session: AsyncSession, *, role_id: uuid.UUID, org_id: uuid.UUID
) -> Role | None:
    """Resolve `role_id` within `org_id` — returns None on miss.

    Pure CRUD primitive. Service-layer callers turn None into the
    HTTP status they need (404 for role-CRUD, 422 for assignment).
    """
    result = await session.execute(select(Role).where(Role.id == role_id, Role.org_id == org_id))
    return result.scalar_one_or_none()


async def get_role_by_id(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    """Resolve a role row by id without an org predicate.

    Used by `users.service.assert_not_owner_role` to check a
    membership's role name when the org is already implicit.
    """
    result = await session.execute(select(Role).where(Role.id == role_id))
    return result.scalar_one_or_none()


async def get_owner_role(session: AsyncSession, org_id: uuid.UUID) -> Role | None:
    """Resolve the Owner role (`is_system=true`, `name='Owner'`) in this org."""
    result = await session.execute(
        select(Role).where(
            Role.org_id == org_id,
            Role.name == "Owner",
            Role.is_system.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_admin_role(session: AsyncSession, org_id: uuid.UUID) -> Role | None:
    """Resolve the Admin role (`name='Admin'`) in this org.

    Admin is `is_system=False` per the template install — Owner can
    rename or delete the row. Returns None when the Owner deleted it;
    callers (e.g. ownership-transfer) must then accept an explicit
    `demote_to_role_id` instead of defaulting to Admin.
    """
    result = await session.execute(select(Role).where(Role.org_id == org_id, Role.name == "Admin"))
    return result.scalar_one_or_none()


# --- offboarding queries ------------------------------------------------


async def list_open_record_ids(
    session: AsyncSession,
    *,
    entity: str,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Resolve the open-record ids for one user + one entity.

    Each entity's "open" predicate is encoded inline here so the
    offboarding orchestrator doesn't depend on every entity service
    exporting its own query helper.

    Predicates:
      - contacts        : every contact assigned to the user (no archival
                          state on contacts)
      - leads           : status = 'active' (the only non-terminal state)
      - walk_ins        : status NOT IN ('converted', 'left')
                          (browsing / interested / follow_up — the three
                          in-store / engaged states)
      - appointments    : status = 'scheduled' AND scheduled_at >= now()
      - tasks           : status != 'done'
    """
    if entity == "contacts":
        stmt = select(Contact.id).where(
            Contact.org_id == org_id,
            Contact.assigned_to_id == user_uuid,
        )
    elif entity == "leads":
        stmt = select(Lead.id).where(
            Lead.org_id == org_id,
            Lead.assigned_to_id == user_uuid,
            Lead.status == LeadStatus.active,
        )
    elif entity == "walk_ins":
        stmt = select(WalkIn.id).where(
            WalkIn.org_id == org_id,
            WalkIn.assigned_to_id == user_uuid,
            WalkIn.status.in_(_WALKIN_OPEN_STATUSES),
        )
    elif entity == "appointments":
        stmt = select(Appointment.id).where(
            Appointment.org_id == org_id,
            Appointment.assigned_to_id == user_uuid,
            Appointment.status == AppointmentStatus.scheduled,
            Appointment.scheduled_at >= datetime.now(UTC),
        )
    elif entity == "tasks":
        stmt = select(Task.id).where(
            Task.org_id == org_id,
            Task.assigned_to_id == user_uuid,
            Task.status != TaskStatus.done,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown entity {entity!r}",
        )
    return list((await session.execute(stmt)).scalars().all())


async def compute_open_records_counts(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, int]:
    """Per-entity open-record counts for the deactivation modal.

    Returns a dict with one key per entity (`contacts`, `leads`,
    `walk_ins`, `appointments`, `tasks`) plus a `total` summing them —
    matches the shape `set_user_status` raises in its 409 detail body.
    """
    counts: dict[str, int] = {}
    for entity in ("contacts", "leads", "walk_ins", "appointments", "tasks"):
        ids = await list_open_record_ids(session, entity=entity, user_uuid=user_uuid, org_id=org_id)
        counts[entity] = len(ids)
    counts["total"] = sum(counts.values())
    return counts


async def list_users_in_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> list[User]:
    """List active users, optionally scoped to one org's active members.

    Joins through `tbl_user_info` to order by email and through
    `tbl_organization_members` to filter on the active flag (and on
    `org_id` if supplied).
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


async def insert_user_login_row(
    session: AsyncSession,
    *,
    legacy_uuid: uuid.UUID,
    user_handle: str,
    password_hash: str,
) -> int:
    """Insert a `tbl_user_login` row via pg_insert.

    The layered `User` mapper excludes the legacy `user_id` text handle
    and the `two_factor_*` columns (they live on the legacy `UserLogin`
    mapper), but both are NOT NULL on the table. Insert at the table
    level so we can populate them; returns the new bigint PK.
    """
    result = await session.execute(
        pg_insert(User.__table__)
        .values(
            legacy_uuid=legacy_uuid,
            user_id=user_handle,
            password=password_hash,
            is_active=True,
            two_factor_enabled=False,
        )
        .returning(User.__table__.c.id)
    )
    return int(result.scalar_one())


async def get_user_by_id(session: AsyncSession, member_id: int) -> User | None:
    """Load the layered `User` mapper for a given `tbl_user_login.id`."""
    result = await session.execute(select(User).where(User.id == member_id))
    return result.scalar_one_or_none()


def add_user_info(session: AsyncSession, info: UserInfo) -> UserInfo:
    """Stage a `tbl_user_info` insert in the current unit-of-work."""
    session.add(info)
    return info


def add_organization_member(
    session: AsyncSession, member: OrganizationMember
) -> OrganizationMember:
    """Stage a `tbl_organization_members` insert in the current unit-of-work."""
    session.add(member)
    return member


async def get_role_name_by_id(session: AsyncSession, role_id: uuid.UUID) -> str | None:
    """Resolve `role_id` to its name. Used by audit-log diff builders."""
    result = await session.execute(select(Role.name).where(Role.id == role_id))
    return result.scalar_one_or_none()


async def update_user_password(
    session: AsyncSession,
    *,
    member_id: int,
    new_hash: str,
) -> None:
    """Write a new bcrypt hash to `tbl_user_login.password` by bigint PK."""
    await session.execute(
        update(User.__table__).where(User.__table__.c.id == member_id).values(password=new_hash)
    )


async def revoke_user_auth_sessions(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    now: datetime,
    except_token_id: uuid.UUID | None = None,
) -> None:
    """Mark every non-revoked `auth_sessions` row for this user as revoked.

    `except_token_id` lets the caller spare the request's own session
    when only "sign out other devices" is wanted.
    """
    stmt = (
        update(AuthSession)
        .where(
            AuthSession.user_id == user_uuid,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    if except_token_id is not None:
        stmt = stmt.where(AuthSession.id != except_token_id)
    await session.execute(stmt)


__all__ = [
    "add_organization_member",
    "add_user_info",
    "compute_open_records_counts",
    "count_active_members",
    "email_exists",
    "get_admin_role",
    "get_membership",
    "get_owner_role",
    "get_role_by_id",
    "get_role_by_id_in_org",
    "get_role_name_by_id",
    "get_user_by_email",
    "get_user_by_id",
    "get_user_by_uuid",
    "get_user_info",
    "insert_user_login_row",
    "list_open_record_ids",
    "list_users_in_org",
    "revoke_user_auth_sessions",
    "update_user_password",
]
