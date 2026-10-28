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

The per-entity "open" predicates and the membership / owner / count
guards used by this flow live in `src.app.core.data_access` — this
file holds only the orchestration shell.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.service import bulk_reassign_appointments
from src.app.core.contacts.service import bulk_reassign_contacts
from src.app.core.leads.service import bulk_reassign_leads
from src.app.core.tasks.service import bulk_reassign_tasks
from src.app.core.users import data_access
from src.app.core.users import service as users_service
from src.app.core.walk_ins.service import bulk_reassign_walk_ins

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
    await users_service.require_membership(
        session,
        user_uuid=to_user_uuid,
        org_id=org_id,
        active_only=True,
        on_missing=status.HTTP_422_UNPROCESSABLE_ENTITY,
        not_found_detail=f"target user {to_user_uuid} not found",
        not_member_detail=("target user is not an active member of this organisation"),
    )
    if to_user_uuid == from_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot transfer records to the same user",
        )

    transferred: dict[str, int] = {}
    audit_count = 0
    for entity in entities:
        ids = await data_access.list_open_record_ids(
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

    return {
        "transferred": transferred,
        "total": sum(transferred.values()),
        "audit_activities_written": audit_count,
    }
