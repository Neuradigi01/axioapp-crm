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
    (``get_membership``, ``require_membership``, ``count_active_members``,
     ``get_role_by_id_in_org``, ``get_role_in_org``, ``get_owner_role``,
     ``get_admin_role``).
  * Offboarding open-record queries
    (``list_open_record_ids``, ``compute_open_records_counts``,
     ``assert_not_owner_role``) — co-located here because they share
    the same per-(user, org) predicate shape.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
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


async def require_membership(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
    active_only: bool = False,
    on_missing: int = status.HTTP_404_NOT_FOUND,
    not_found_detail: str | None = None,
    not_member_detail: str | None = None,
) -> tuple[User, OrganizationMember]:
    """Resolve user-UUID → User → OrganizationMember in this org.

    Raises `HTTPException(status_code=on_missing, ...)` if the user
    doesn't exist or has no matching membership. Returns the
    `(User, OrganizationMember)` pair so callers can keep working with
    both without re-querying.

    `on_missing` controls the response code:
      - 404 (default) : "user X not found" / "not a member of this org"
                        — for admin CRUD paths where the caller has the
                        right to know whether the resource exists.
      - 422           : validation failure — used by ownership-transfer
                        target validation, offboarding's target check.
      - 403           : authorization failure — caller themselves has no
                        membership in the org they're trying to act on.
    """
    user = await get_user_by_uuid(session, user_uuid)
    if user is None:
        raise HTTPException(
            status_code=on_missing,
            detail=not_found_detail or f"user {user_uuid} not found",
        )
    membership = await get_membership(
        session,
        user_member_id=user.id,
        org_id=org_id,
        active_only=active_only,
    )
    if membership is None:
        raise HTTPException(
            status_code=on_missing,
            detail=not_member_detail
            or f"user {user_uuid} is not a member of this org",
        )
    return user, membership


async def count_active_members(
    session: AsyncSession, org_id: uuid.UUID
) -> int:
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

    The non-raising sibling of `get_role_in_org`. Callers that need
    a specific HTTP status (e.g. 404 for the role-CRUD endpoints, 422
    for assignment validation) build the right exception themselves.
    """
    result = await session.execute(
        select(Role).where(Role.id == role_id, Role.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_role_in_org(
    session: AsyncSession, *, role_id: uuid.UUID, org_id: uuid.UUID
) -> Role:
    """Resolve `role_id` within `org_id`. Raises 422 if not found.

    Used by user-create / user-update to validate the caller's chosen
    role assignment before persisting it.
    """
    role = await get_role_by_id_in_org(
        session, role_id=role_id, org_id=org_id
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role_id {role_id} not found in this org",
        )
    return role


async def get_owner_role(
    session: AsyncSession, org_id: uuid.UUID
) -> Role | None:
    """Resolve the Owner role (`is_system=true`, `name='Owner'`) in this org."""
    result = await session.execute(
        select(Role).where(
            Role.org_id == org_id,
            Role.name == "Owner",
            Role.is_system.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_admin_role(
    session: AsyncSession, org_id: uuid.UUID
) -> Role | None:
    """Resolve the Admin role (`name='Admin'`) in this org.

    Admin is `is_system=False` per the template install — Owner can
    rename or delete the row. Returns None when the Owner deleted it;
    callers (e.g. ownership-transfer) must then accept an explicit
    `demote_to_role_id` instead of defaulting to Admin.
    """
    result = await session.execute(
        select(Role).where(Role.org_id == org_id, Role.name == "Admin")
    )
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
            Appointment.scheduled_at >= datetime.now(timezone.utc),
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
        ids = await list_open_record_ids(
            session, entity=entity, user_uuid=user_uuid, org_id=org_id
        )
        counts[entity] = len(ids)
    counts["total"] = sum(counts.values())
    return counts


async def assert_not_owner_role(
    session: AsyncSession,
    *,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Refuse deactivation of the Owner. Mirrors the `rbac-ownership/`
    rule: the Owner must transfer ownership before being deactivated.

    Raises 403 (not 422) because this is an authorisation-level
    invariant — the caller can't bypass it regardless of input.
    Silent-returns on user-not-found / not-in-org so the upstream guard
    can surface those with its own (typically 404) error.
    """
    user = await get_user_by_uuid(session, user_uuid)
    if user is None:
        return
    membership = await get_membership(
        session, user_member_id=user.id, org_id=org_id
    )
    if membership is None:
        return
    role = (
        await session.execute(
            select(Role).where(Role.id == membership.role_id)
        )
    ).scalar_one_or_none()
    if role is None:
        return
    if role.name == "Owner" and role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "the workspace Owner cannot be deactivated — "
                "transfer ownership first"
            ),
        )


__all__ = [
    "assert_not_owner_role",
    "compute_open_records_counts",
    "count_active_members",
    "email_exists",
    "get_admin_role",
    "get_membership",
    "get_owner_role",
    "get_role_by_id_in_org",
    "get_role_in_org",
    "get_user_by_email",
    "get_user_by_uuid",
    "get_user_info",
    "list_open_record_ids",
    "require_membership",
]
