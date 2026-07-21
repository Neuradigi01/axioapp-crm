"""Service layer for walk-ins.

Three responsibilities:

1. **Standard CRUD** with `custom_data` validation against
   `custom_field_definitions` for `entity_type='walk_in'`. Same
   pattern as contacts / leads / appointments.
2. **`quick_register`** — the reception-desk one-shot. Looks up an
   existing contact by `(org_id, phone)`; if found, reuses it. If
   missing, creates a minimal contact row. Then creates the walk-in.
3. **`checkout`** — stamps `time_out=now()`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.activities.models import ActivityType
from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import LeadSource
from src.app.core.walk_ins import data_access as _da
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.core.walk_ins.schemas import (
    QuickRegisterPayload,
    WalkInCreate,
    WalkInUpdate,
)
from src.app.core.walk_ins.status_workflow import ALLOWED_TRANSITIONS
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found

_WALK_IN_ENTITY = "walk_in"


_SNAPSHOT_FIELDS = (
    "id",
    "contact_id",
    "time_in",
    "time_out",
    "requirement",
    "budget",
    "assigned_to_id",
    "status",
    "notes",
    "custom_data",
    "party_size",
    "wait_started_at",
    "expected_return_date",
    "linked_lead_id",
)


def _snapshot(w: WalkIn) -> dict[str, Any]:
    return snapshot(w, fields=_SNAPSHOT_FIELDS)


# --- helpers ---


async def _ensure_contact_in_scope(session: AsyncSession, contact_id: uuid.UUID) -> None:
    if not await _da.contact_exists_in_org(session, contact_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contact_id {contact_id} not found in this org",
        )


async def _find_contact_by_phone(session: AsyncSession, phone: str) -> Contact | None:
    # Exact phone match — reception desk's natural dedup key. The
    # ORM's tenant filter already scopes to the active org.
    normalized = phone.strip()
    if not normalized:
        return None
    return await contacts_service.get_contact_by_phone(session, normalized)


# --- CRUD ---


async def get_walk_in(session: AsyncSession, walk_in_id: uuid.UUID) -> WalkIn | None:
    return await _da.get_walk_in_by_id(session, walk_in_id)


async def create_walk_in(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: WalkInCreate,
) -> WalkIn:
    await _ensure_contact_in_scope(session, payload.contact_id)
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_WALK_IN_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
    )
    walk_in = WalkIn(
        org_id=org_id,
        contact_id=payload.contact_id,
        requirement=payload.requirement,
        budget=payload.budget,
        assigned_to_id=payload.assigned_to_id,
        notes=payload.notes,
        status=WalkInStatus.browsing,
        custom_data=cleaned_custom,
        party_size=payload.party_size,
        wait_started_at=payload.wait_started_at,
        expected_return_date=payload.expected_return_date,
    )
    _da.insert_walk_in(session, walk_in)
    await session.commit()
    await session.refresh(walk_in)

    await log_entity_change(
        action="walk_ins.created",
        entity_type="walk_in",
        entity_id=walk_in.id,
        after=_snapshot(walk_in),
    )
    return walk_in


async def update_walk_in(
    session: AsyncSession,
    *,
    walk_in_id: uuid.UUID,
    payload: WalkInUpdate,
    org_id: uuid.UUID | None = None,
) -> WalkIn:
    """Partial update.

    `org_id` is optional for back-compat, but when supplied the service
    enforces cross-tenant safety on `assigned_to_id` — a caller with
    `walkins.write` cannot reassign a walk-in to a user that isn't an
    active member of their own org. Complements the router-side
    `walkins.reassign` permission check.
    """
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")

    before = _snapshot(walk_in)
    changes = payload.model_dump(exclude_unset=True)

    if (
        "assigned_to_id" in changes
        and changes["assigned_to_id"] is not None
        and org_id is not None
    ):
        await _assert_user_in_org(
            session, org_id=org_id, user_uuid=changes["assigned_to_id"]
        )

    # State-machine enforcement: only allow status transitions declared
    # in `ALLOWED_TRANSITIONS`. Identity transitions (X → X) are no-ops
    # at the data layer but we accept them so a PATCH that re-sends the
    # current status alongside other field changes still succeeds.
    if "status" in changes and changes["status"] is not None:
        new_status = changes["status"]
        new_value = new_status.value if isinstance(new_status, WalkInStatus) else str(new_status)
        current = walk_in.status.value
        if new_value != current:
            allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
            if new_value not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"invalid walk-in status transition {current!r} → {new_value!r}"),
                )

    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_WALK_IN_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    for key, value in changes.items():
        setattr(walk_in, key, value)
    await session.commit()
    await session.refresh(walk_in)

    await log_entity_change(
        action="walk_ins.updated",
        entity_type="walk_in",
        entity_id=walk_in.id,
        before=before,
        after=_snapshot(walk_in),
    )
    return walk_in


async def delete_walk_in(session: AsyncSession, *, walk_in_id: uuid.UUID) -> None:
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")
    before = _snapshot(walk_in)
    walk_in_uuid = walk_in.id
    await _da.delete_walk_in_row(session, walk_in)
    await session.commit()

    await log_entity_change(
        action="walk_ins.deleted",
        entity_type="walk_in",
        entity_id=walk_in_uuid,
        before=before,
    )


async def list_walk_ins(
    session: AsyncSession,
    *,
    status_filter: WalkInStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    open_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["time_in", "created_at", "last_activity_at"] = "time_in",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[WalkIn], int]:
    """Paginated list with filters."""
    return await _da.list_walk_ins_paginated(
        session,
        status_filter=status_filter,
        assigned_to=assigned_to,
        open_only=open_only,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        order=order,
        page=page,
        size=size,
    )


async def list_walk_ins_visible_to(
    session: AsyncSession,
    *,
    caller,
    status_filter: WalkInStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    open_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["time_in", "created_at", "last_activity_at"] = "time_in",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[WalkIn], int]:
    """Row-level visibility wrapper.

    Callers without `users.read` (employees vs. managers) only see
    walk-ins assigned to them. Any `assigned_to=<other>` they pass
    is silently clamped to self. Business rule — moved out of the
    router so this is the single point of enforcement.
    """
    from src.app.core.permissions.service import role_has_permission

    if not await role_has_permission(session, caller.role_id, "users.read"):
        assigned_to = caller.legacy_uuid
    return await list_walk_ins(
        session,
        status_filter=status_filter,
        assigned_to=assigned_to,
        open_only=open_only,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        order=order,
        page=page,
        size=size,
    )


# --- quick_register + checkout ---


async def quick_register(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: QuickRegisterPayload,
) -> tuple[WalkIn, Contact, bool]:
    """Reception-desk one-shot. Returns (walk_in, contact, was_created)."""
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_WALK_IN_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
    )

    existing = await _find_contact_by_phone(session, payload.phone)
    was_created = False
    if existing is not None:
        contact = existing
    else:
        contact = Contact(
            org_id=org_id,
            full_name=payload.full_name,
            phone=payload.phone,
            email=payload.email,
            source=payload.source,
            tags=[],
            custom_data={},
        )
        contacts_service.insert_contact(session, contact)
        await session.flush()
        was_created = True

    walk_in = WalkIn(
        org_id=org_id,
        contact_id=contact.id,
        requirement=payload.requirement,
        budget=payload.budget,
        assigned_to_id=payload.assigned_to_id,
        notes=payload.notes,
        status=WalkInStatus.browsing,
        custom_data=cleaned_custom,
        party_size=payload.party_size,
        wait_started_at=payload.wait_started_at,
        expected_return_date=payload.expected_return_date,
    )
    _da.insert_walk_in(session, walk_in)
    await session.commit()
    await session.refresh(walk_in)

    await audit.log(
        "walk_ins.quick_registered",
        entity_type="walk_in",
        entity_id=walk_in.id,
        after={
            **_snapshot(walk_in),
            "contact_was_created": was_created,
        },
    )
    return walk_in, contact, was_created


async def checkout(session: AsyncSession, *, walk_in_id: uuid.UUID) -> WalkIn:
    """Stamp `time_out=now()` on a walk-in. Idempotent."""
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")
    if walk_in.time_out is None:
        before = _snapshot(walk_in)
        walk_in.time_out = datetime.now(UTC)
        await session.commit()
        await session.refresh(walk_in)
        await audit.log(
            "walk_ins.checked_out",
            entity_type="walk_in",
            entity_id=walk_in.id,
            before=before,
            after=_snapshot(walk_in),
        )
    return walk_in


# --- Reassign / bulk-action / convert --------------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org."""
    if not await _da.user_has_active_membership(session, org_id=org_id, user_uuid=user_uuid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def reassign_walk_in(
    session: AsyncSession,
    *,
    walk_in_id: uuid.UUID,
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> WalkIn:
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")
    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    before_id = walk_in.assigned_to_id
    if before_id == assigned_to_id:
        return walk_in

    before = _snapshot(walk_in)
    walk_in.assigned_to_id = assigned_to_id
    await activities.record_in_session(
        session,
        org_id=org_id,
        entity_type="walk_in",
        entity_id=walk_in.id,
        type=ActivityType.reassign,
        payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
        user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(walk_in)

    await audit.log(
        "walk_ins.reassigned",
        entity_type="walk_in",
        entity_id=walk_in.id,
        before=before,
        after=_snapshot(walk_in),
    )
    return walk_in


async def bulk_reassign_walk_ins(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[int, int]:
    """Reassign N walk-ins in one transaction.

    Returns `(reassigned, already_assigned)` so the caller can render
    an honest "X reassigned, Y already owned this seat" summary
    instead of silently dropping the second bucket.

    Batched SELECT via `list_walk_ins_by_ids_in_org` collapses the old
    per-id N+1 fetch. Activity inserts stay per-row (each timeline
    needs its own entry).
    """
    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    walk_ins = await _da.list_walk_ins_by_ids_in_org(session, ids=ids, org_id=org_id)

    reassigned = 0
    already_assigned = 0
    for walk_in in walk_ins:
        if walk_in.assigned_to_id == assigned_to_id:
            already_assigned += 1
            continue
        before_id = walk_in.assigned_to_id
        walk_in.assigned_to_id = assigned_to_id
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type="walk_in",
            entity_id=walk_in.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
            user_id=actor_user_id,
        )
        reassigned += 1

    await session.commit()
    return reassigned, already_assigned


async def bulk_checkout_walk_ins(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> tuple[int, int]:
    """Bulk equivalent of single-row `checkout`.

    Batched: fetch every referenced row in one SELECT, split into
    "already checked out" vs "needs stamp", then apply the stamps
    to the ORM instances so `updated_at` + audit-log columns fire
    normally. Previous per-id loop was O(N) round-trips.
    """
    now_ts = datetime.now(UTC)
    walk_ins = await _da.list_walk_ins_by_ids_in_org(session, ids=ids, org_id=org_id)

    checked_out = 0
    already_out = 0
    for walk_in in walk_ins:
        if walk_in.time_out is not None:
            already_out += 1
            continue
        walk_in.time_out = now_ts
        checked_out += 1

    await session.commit()
    return checked_out, already_out


async def convert_walk_in_to_lead(
    session: AsyncSession,
    *,
    walk_in_id: uuid.UUID,
    org_id: uuid.UUID,
    contact_link_mode: str,
    linked_contact_id: uuid.UUID | None,
    notes: str | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[WalkIn, uuid.UUID, uuid.UUID]:
    """Spin up a `Lead` from a walk-in."""
    # Imported lazily to avoid a circular import at module load.
    from src.app.core.leads.schemas import LeadCreate
    from src.app.core.leads.service import create_lead as create_lead_service

    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")
    if walk_in.linked_lead_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "walk-in already converted",
                "lead_id": str(walk_in.linked_lead_id),
            },
        )

    # Resolve contact.
    if contact_link_mode == "link":
        if linked_contact_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="linked_contact_id is required when contact_link_mode='link'",
            )
        await _ensure_contact_in_scope(session, linked_contact_id)
        contact_id = linked_contact_id
    else:
        # auto — keep the walk-in's existing linked contact
        contact_id = walk_in.contact_id

    lead_payload = LeadCreate(
        contact_id=contact_id,
        assigned_to_id=walk_in.assigned_to_id,
        budget=walk_in.budget,
        custom_data={},  # walk-in.custom_data is walk-in-shaped, not lead-shaped
        # Stamp `walk_in` provenance so downstream attribution reports
        # keyed on `Lead.source` can tell hand-typed manual leads from
        # walk-in conversions. `Lead.source_walk_in_id` remains the
        # FK-backed backlink for detail-page rendering.
        source=LeadSource.walk_in,
    )
    lead = await create_lead_service(
        session,
        org_id=org_id,
        payload=lead_payload,
        require_all_required=False,
    )

    walk_in.linked_lead_id = lead.id
    # W6 — stamp the reverse-link on the fresh Lead so a lead-detail
    # page can render "originated from walk-in on X" and win-attribution
    # analytics can walk backwards from a closed deal.
    lead.source_walk_in_id = walk_in.id
    await activities.record_in_session(
        session,
        org_id=org_id,
        entity_type="walk_in",
        entity_id=walk_in.id,
        type=ActivityType.convert,
        payload={
            "contact_id": str(contact_id),
            "lead_id": str(lead.id),
            "notes": notes,
        },
        user_id=actor_user_id,
    )
    # W4 — auto-create a follow-up task on the new lead so reps don't
    # forget to circle back. Due tomorrow (24h out) so it lands on
    # today's follow-ups widget for the rep's next-morning triage.
    # Defensive try/except: task-create must not roll back the
    # already-committed conversion — a Task insert failure logs and
    # continues (rep can add the task manually).
    from datetime import timedelta

    from src.app.core.tasks.data_access import insert_task
    from src.app.core.tasks.models import Task, TaskFollowupType, TaskPriority

    try:
        follow_up = Task(
            org_id=org_id,
            title=f"Follow up on new lead (from walk-in)",
            description=(
                (notes or "").strip() or "Auto-created when the walk-in was converted."
            ),
            due_at=datetime.now(UTC) + timedelta(days=1),
            assigned_to_id=walk_in.assigned_to_id or actor_user_id,
            related_entity_type="lead",
            related_entity_id=lead.id,
            priority=TaskPriority.med,
            followup_type=TaskFollowupType.other,
        )
        insert_task(session, follow_up)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "walk_ins.convert auto-task creation failed org=%s walk_in=%s lead=%s",
            org_id,
            walk_in.id,
            lead.id,
        )
    await session.commit()
    await session.refresh(walk_in)

    await audit.log(
        "walk_ins.converted",
        entity_type="walk_in",
        entity_id=walk_in.id,
        after={
            **_snapshot(walk_in),
            "lead_id": str(lead.id),
            "contact_id": str(contact_id),
        },
    )

    return walk_in, contact_id, lead.id


async def bulk_delete_walk_ins(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """W1 — Bulk-delete N walk-ins in one SQL statement.

    Mirror of ``leads.service.bulk_delete_leads``. Belt + suspenders:
    the DAL query filters by both the id list *and* ``org_id`` — RLS
    would already scope us, but the explicit clause is defence in
    depth against a mis-scoped session. Single audit row groups the
    action ("bulk-delete of N walk-ins") rather than emitting one
    audit per id.
    """
    rowcount = await _da.delete_walk_ins_in_org(session, ids=ids, org_id=org_id)
    if rowcount == 0:
        return 0
    await session.commit()

    await audit.log(
        "walk_ins.bulk_deleted",
        entity_type="walk_in",
        # entity_id intentionally omitted — the action spans N rows.
        after={"deleted_count": rowcount, "ids": [str(i) for i in ids]},
    )
    return rowcount


async def walk_ins_rollup(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    assigned_to: uuid.UUID | None,
) -> dict[str, Any]:
    """W7 — Server-side KPI roll-up for the walk-ins page header.

    Scope: when ``assigned_to`` is supplied, sums only that user's
    walk-ins (personal roll-up). When None, org-wide. Caller (router)
    decides which based on ``users.read``.

    "Today" is IST-anchored (+330 min from UTC) so IST orgs don't
    roll over at 5:30 AM local. Multi-tz support is a future step —
    when we add `org.timezone`, the service resolves that to an offset
    and passes it to the DAL.
    """
    row = await _da.rollup_query(
        session,
        org_id=org_id,
        assigned_to=assigned_to,
        day_boundary_offset_minutes=330,  # IST
    )
    return {
        "today_count": int(row.today_count or 0),
        "today_converted": int(row.today_converted or 0),
        "open_now": int(row.open_now or 0),
        "interested_or_follow_up": int(row.interested_or_follow_up or 0),
        "conversion_rate_pct": (
            float(row.conversion_rate_pct) if row.conversion_rate_pct is not None else None
        ),
        "avg_duration_min": (
            float(row.avg_duration_min) if row.avg_duration_min is not None else None
        ),
        "avg_wait_min": (
            float(row.avg_wait_min) if row.avg_wait_min is not None else None
        ),
    }


__all__ = [
    "WalkInStatus",
    "bulk_checkout_walk_ins",
    "bulk_delete_walk_ins",
    "bulk_reassign_walk_ins",
    "checkout",
    "convert_walk_in_to_lead",
    "create_walk_in",
    "delete_walk_in",
    "get_walk_in",
    "list_walk_ins",
    "quick_register",
    "reassign_walk_in",
    "update_walk_in",
    "walk_ins_rollup",
]
