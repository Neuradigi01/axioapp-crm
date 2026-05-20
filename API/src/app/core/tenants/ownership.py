"""Ownership transfer — atomic Owner-row swap.

The caller (current Owner) hands their org over to another active
member. Net effect in one transaction:

  - caller's `tbl_organization_members.role_id` ← `demote_to_role_id`
    (defaults to the org's Admin role)
  - target's `tbl_organization_members.role_id` ← Owner role
  - one `ownership.transferred` audit row written with both sides

Authorization is intentionally *not* gated on a permission key — Owner
is fixed (CLAUDE.md / rule 7), so handing the keys to anyone holding
`users.write` would let Admins seize the org. Only the actual Owner of
this org can fire this endpoint, enforced here by checking the
caller's `Role.name == 'Owner' AND is_system=True` row.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.permissions.models import Role
from src.app.core.users.models import OrganizationMember, User


class _Forbidden(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class _Invalid(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


async def _owner_role_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> Role | None:
    return (
        await session.execute(
            select(Role).where(
                Role.org_id == org_id,
                Role.name == "Owner",
                Role.is_system.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _admin_role_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> Role | None:
    """The Admin role as installed by the template — `is_system=False`.

    Returns None when the Owner deleted Admin from the Roles page. The
    transfer caller must then pass an explicit `demote_to_role_id`.
    """
    return (
        await session.execute(
            select(Role).where(Role.org_id == org_id, Role.name == "Admin")
        )
    ).scalar_one_or_none()


async def transfer_ownership(
    session: AsyncSession,
    *,
    caller: User,
    target_user_uuid: uuid.UUID,
    demote_to_role_id: uuid.UUID | None,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[OrganizationMember, OrganizationMember]:
    """Atomically swap Owner from caller → target. Returns `(new_owner, demoted)`."""
    org_id = caller.org_id
    if org_id is None:
        raise _Forbidden("Caller has no active org membership.")

    owner_role = await _owner_role_for_org(session, org_id)
    if owner_role is None:
        raise _Invalid("This org has no Owner role — cannot transfer.")

    # Caller must be the current Owner — checked off their role, not a
    # permission key. Admin holding `users.write` is NOT enough.
    if caller.role_id != owner_role.id:
        raise _Forbidden("Only the Owner can transfer ownership.")

    if caller.legacy_uuid == target_user_uuid:
        raise _Invalid("Cannot transfer ownership to yourself.")

    # Resolve target by UUID → bigint id → membership row in this org.
    target_user_id_row = (
        await session.execute(
            select(User.id).where(User.legacy_uuid == target_user_uuid)
        )
    ).scalar_one_or_none()
    if target_user_id_row is None:
        raise _Invalid("Target user not found.")

    target_membership = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_member_id == target_user_id_row,
                OrganizationMember.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if target_membership is None:
        raise _Invalid("Target is not an active member of this org.")
    if target_membership.role_id == owner_role.id:
        raise _Invalid(
            "Target is already Owner — multiple Owner rows detected. "
            "Contact support."
        )

    # Resolve caller's own membership row (the one we'll demote).
    caller_membership = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_member_id == caller.id,
                OrganizationMember.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if caller_membership is None:
        raise _Forbidden("Caller has no active membership row to demote.")

    # Resolve demote role.
    if demote_to_role_id is None:
        admin_role = await _admin_role_for_org(session, org_id)
        if admin_role is None:
            raise _Invalid(
                "No Admin role exists in this org. Pass demote_to_role_id "
                "explicitly with the role you want for yourself."
            )
        demote_role = admin_role
    else:
        demote_role = (
            await session.execute(
                select(Role).where(
                    Role.org_id == org_id, Role.id == demote_to_role_id
                )
            )
        ).scalar_one_or_none()
        if demote_role is None:
            raise _Invalid(
                f"demote_to_role_id {demote_to_role_id} is not a role in this org."
            )
        if demote_role.id == owner_role.id:
            raise _Invalid("demote_to_role_id cannot be the Owner role.")

    # Atomic swap. Both UPDATEs share the same outer transaction.
    before = {
        "caller_role_id": str(caller_membership.role_id),
        "target_role_id": str(target_membership.role_id),
    }
    caller_membership.role_id = demote_role.id
    target_membership.role_id = owner_role.id

    await session.commit()
    await session.refresh(caller_membership)
    await session.refresh(target_membership)

    await audit.log(
        "ownership.transferred",
        entity_type="organization",
        entity_id=org_id,
        before=before,
        after={
            "new_owner_user_uuid": str(target_user_uuid),
            "demoted_user_uuid": str(caller.legacy_uuid),
            "demoted_to_role_id": str(demote_role.id),
            "demoted_to_role_name": demote_role.name,
        },
        ip=ip,
        ua=ua,
    )

    return target_membership, caller_membership
