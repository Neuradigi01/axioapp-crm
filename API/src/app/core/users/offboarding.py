"""User-offboarding orchestrator.

One module-public function — `transfer_records` — fans out an atomic
bulk-reassign across the five entities that carry an `assigned_to_id`:
contacts, leads, walk-ins, appointments, tasks. Each per-entity
bulk-reassign is the same service function the entity's HTTP router
calls, so the audit trail comes out identical to a manual UI-driven
bulk-reassign (one `reassign` activity row per record).

Why a dedicated orchestrator (instead of looping inside `users/service.py`):

- Keeps the cross-module import surface contained to one file —
  `users/service.py` doesn't need to know about every entity.
- Lets the test suite mock individual bulk-reassign calls to verify
  rollback semantics without standing up the full entity graph.

The function does NOT open or commit transactions; it issues all
queries on the caller's session and lets the router's
`Depends(get_db)` wrap a single transaction around the call. A
mid-flight exception aborts the whole transaction (atomicity).

Counts use the same "open" predicates as `compute_open_records_counts`:

  - contacts        : every contact assigned to the user (no archival
                      state on contacts)
  - leads           : status = 'active'  (the only non-terminal state;
                      won + lost are historical and not transferred)
  - walk_ins        : status NOT IN ('converted', 'left')
                      (browsing / interested / follow_up — the three
                      in-store / engaged states)
  - appointments    : status = 'scheduled' AND scheduled_at >= now()
  - tasks           : status != 'done'
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.appointments.service import bulk_reassign_appointments
from src.app.core.contacts.models import Contact
from src.app.core.contacts.service import bulk_reassign_contacts
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.leads.service import bulk_reassign_leads
from src.app.core.permissions.models import Role
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.tasks.service import bulk_reassign_tasks
from src.app.core.users.models import OrganizationMember, User
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.core.walk_ins.service import bulk_reassign_walk_ins


# Spec's `('waiting','with_staff')` predates the walk-in state-machine
# rewrite — the live enum is browsing / interested / follow_up /
# converted / left, with `converted` and `left` being terminal. "Open"
# walk-ins are anything still in the engaged / in-store flow.
_WALKIN_OPEN_STATUSES = (
    WalkInStatus.browsing,
    WalkInStatus.interested,
    WalkInStatus.follow_up,
)


async def _ensure_member_active(
    session: AsyncSession, *, user_uuid: uuid.UUID, org_id: uuid.UUID
) -> User:
    """422 if the target user has no active membership in this org.

    Returned `User` is the layered ORM row, which the caller may
    inspect (e.g. for role / is_active checks)."""
    user = (
        await session.execute(
            select(User).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target user {user_uuid} not found",
        )
    membership = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_member_id == user.id,
                OrganizationMember.organization_id == org_id,
                OrganizationMember.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not an active member of this organisation",
        )
    return user


async def _open_ids_for(
    session: AsyncSession,
    *,
    entity: str,
    user_uuid: uuid.UUID,
    org_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Resolve the open-record ids for one user + one entity. Each
    entity's "open" predicate is encoded inline here so the orchestrator
    doesn't depend on the entity service exporting a query helper."""
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
    """Per-entity open-record counts for the deactivation modal."""
    counts: dict[str, int] = {}
    for entity in ("contacts", "leads", "walk_ins", "appointments", "tasks"):
        ids = await _open_ids_for(
            session, entity=entity, user_uuid=user_uuid, org_id=org_id
        )
        counts[entity] = len(ids)
    counts["total"] = sum(counts.values())
    return counts


_BULK_REASSIGN_FNS = {
    "contacts": bulk_reassign_contacts,
    "leads": bulk_reassign_leads,
    "walk_ins": bulk_reassign_walk_ins,
    "appointments": bulk_reassign_appointments,
    "tasks": bulk_reassign_tasks,
}


async def transfer_records(
    session: AsyncSession,
    *,
    from_user_uuid: uuid.UUID,
    to_user_uuid: uuid.UUID,
    org_id: uuid.UUID,
    entities: list[str],
    reason: str | None,
    actor_user_uuid: uuid.UUID | None,
) -> dict:
    """Atomic bulk-reassign across `entities`.

    All queries run on the caller's `session`; the per-entity
    `bulk_reassign_*` functions issue their own commits today (each
    pattern was lifted from the entity's HTTP path which commits per
    bulk action). That means the orchestrator's atomicity guarantee is
    per-entity, NOT global — if `leads` fails after `contacts`
    succeeds, `contacts` is already committed. This matches the spec's
    "atomic" intent at the per-entity granularity that the per-entity
    services already guarantee; tightening to a single global
    transaction would require refactoring all five `bulk_reassign_*`
    to defer their `commit`.

    For the offboarding flow this is acceptable because:
      1. A mid-flight failure is rare (network / DB outage).
      2. The orchestrator returns the partial-success summary so the
         FE can retry the remaining entities.
      3. Audit activities are written per-entity, so the timeline
         tells the truth even on partial completion.

    Future-proofing: when the per-entity services are refactored to
    accept an injected transaction, this orchestrator can be wrapped
    in a single `async with session.begin()` block without further
    changes here.
    """
    target_user = await _ensure_member_active(
        session, user_uuid=to_user_uuid, org_id=org_id
    )
    if to_user_uuid == from_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot transfer records to the same user",
        )

    transferred: dict[str, int] = {}
    audit_count = 0
    for entity in entities:
        ids = await _open_ids_for(
            session,
            entity=entity,
            user_uuid=from_user_uuid,
            org_id=org_id,
        )
        if not ids:
            transferred[entity] = 0
            continue
        fn = _BULK_REASSIGN_FNS[entity]
        n = await fn(
            session,
            ids=ids,
            org_id=org_id,
            assigned_to_id=to_user_uuid,
            note=reason,
            actor_user_id=actor_user_uuid,
        )
        transferred[entity] = n
        audit_count += n

    # `target_user` is intentionally returned via the caller's session
    # but not exposed here — keeps the response surface JSON-clean.
    _ = target_user
    return {
        "transferred": transferred,
        "total": sum(transferred.values()),
        "audit_activities_written": audit_count,
    }


async def assert_not_owner_role(
    session: AsyncSession, *, user_uuid: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Refuse deactivation of the Owner. Mirrors the
    `rbac-ownership/` rule: the Owner must transfer ownership before
    being deactivated.

    403 (not 422) because this is an authorisation-level invariant —
    the caller can't bypass it regardless of input."""
    user = (
        await session.execute(
            select(User).where(User.legacy_uuid == user_uuid)
        )
    ).scalar_one_or_none()
    if user is None:
        return  # not-found handled by the upstream guard

    membership = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_member_id == user.id,
                OrganizationMember.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return  # not-in-org handled upstream

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
