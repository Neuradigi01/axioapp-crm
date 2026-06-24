"""Service layer for walk-ins.

Three responsibilities:

1. **Standard CRUD** with `custom_data` validation against
   `custom_field_definitions` for `entity_type='walk_in'`. Same
   pattern as contacts / leads / appointments.
2. **`quick_register`** — the reception-desk one-shot. Looks up an
   existing contact by `(org_id, phone)`; if found, reuses it. If
   missing, creates a minimal contact row. Then creates the walk-in.
   Returns the walk-in plus the resolved contact so the UI can show
   prior tags/source on the first paint.
3. **`checkout`** — stamps `time_out=now()`. The model's STORED
   generated column computes `duration_min` automatically when the
   row is re-read.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts import data_access
from src.app.core.activities.models import Activity, ActivityType
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadSource, LeadStatus
from src.app.core.users.models import OrganizationMember, User
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.core.walk_ins.schemas import (
    QuickRegisterPayload,
    WalkInCreate,
    WalkInUpdate,
)
from src.app.core.walk_ins.status_workflow import ALLOWED_TRANSITIONS
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import ensure_found


_WALK_IN_ENTITY = "walk_in"


# Server-side sort whitelist. The router rejects anything outside via
# FastAPI Literal validation; the service uses this dict to resolve key
# → SQLA column without exposing arbitrary attribute access.
_SORT_COLUMNS = {
    "time_in": WalkIn.time_in,
    "created_at": WalkIn.created_at,
    "last_activity_at": WalkIn.last_activity_at,
}


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
)


def _snapshot(w: WalkIn) -> dict[str, Any]:
    return snapshot(w, fields=_SNAPSHOT_FIELDS)


# --- custom_data validation (mirrors contacts / leads / appointments) ---


# --- helpers ---


async def _ensure_contact_in_scope(
    session: AsyncSession, contact_id: uuid.UUID
) -> None:
    contact = (
        await session.execute(select(Contact.id).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contact_id {contact_id} not found in this org",
        )


async def _find_contact_by_phone(
    session: AsyncSession, phone: str
) -> Optional[Contact]:
    # Exact phone match — reception desk's natural dedup key. The
    # ORM's tenant filter already scopes to the active org.
    normalized = phone.strip()
    if not normalized:
        return None
    return await data_access.get_contact_by_phone(session, normalized)


# --- CRUD ---


async def get_walk_in(
    session: AsyncSession, walk_in_id: uuid.UUID
) -> Optional[WalkIn]:
    result = await session.execute(select(WalkIn).where(WalkIn.id == walk_in_id))
    return result.scalar_one_or_none()


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
    )
    session.add(walk_in)
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
) -> WalkIn:
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")

    before = _snapshot(walk_in)
    changes = payload.model_dump(exclude_unset=True)

    # State-machine enforcement: only allow status transitions declared
    # in `ALLOWED_TRANSITIONS`. Identity transitions (X → X) are no-ops
    # at the data layer but we accept them so a PATCH that re-sends the
    # current status alongside other field changes still succeeds.
    if "status" in changes and changes["status"] is not None:
        new_status = changes["status"]
        # Pydantic deserialises status as WalkInStatus when typed; allow
        # either the enum or its `.value` string to flow through.
        new_value = (
            new_status.value
            if isinstance(new_status, WalkInStatus)
            else str(new_status)
        )
        current = walk_in.status.value
        if new_value != current:
            allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
            if new_value not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"invalid walk-in status transition "
                        f"{current!r} → {new_value!r}"
                    ),
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
    await session.delete(walk_in)
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
    status_filter: Optional[WalkInStatus] = None,
    assigned_to: Optional[uuid.UUID] = None,
    open_only: bool = False,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort: Literal["time_in", "created_at", "last_activity_at"] = "time_in",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[WalkIn], int]:
    """Paginated list with filters.

    - `status_filter` / `assigned_to` — exact-match scoping.
    - `open_only=True` filters to rows with no `time_out` (currently
      in-store). Front-desk dashboards default this on.
    - `date_from` / `date_to` — `time_in` window. Powers the
      "Today / This week / This month" FE chips (Step 2).
    - `sort` is server-whitelisted via `_SORT_COLUMNS`.
      `last_activity_at desc` appends `NULLS LAST` so never-touched
      walk-ins sink to the bottom.
    """
    filters: list[Any] = []
    if status_filter is not None:
        filters.append(WalkIn.status == status_filter)
    if assigned_to is not None:
        filters.append(WalkIn.assigned_to_id == assigned_to)
    if open_only:
        filters.append(WalkIn.time_out.is_(None))
    if date_from is not None:
        filters.append(WalkIn.time_in >= date_from)
    if date_to is not None:
        filters.append(WalkIn.time_in <= date_to)

    where = and_(*filters) if filters else None

    base = select(WalkIn)
    if where is not None:
        base = base.where(where)

    sort_col = _SORT_COLUMNS[sort]
    if sort == "last_activity_at":
        primary = sort_col.asc().nulls_last() if order == "asc" else sort_col.desc().nulls_last()
    else:
        primary = sort_col.asc() if order == "asc" else sort_col.desc()
    base = base.order_by(primary, WalkIn.id.desc())

    return await paginate(session, base, page=page, size=size)


# --- quick_register + checkout ---


async def quick_register(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: QuickRegisterPayload,
) -> tuple[WalkIn, Contact, bool]:
    """Reception-desk one-shot. Returns (walk_in, contact, was_created).

    Phone is the dedup key — if a contact in this org already has the
    same `phone`, we reuse it (no merge of name/email). Otherwise we
    create a minimal contact row directly (bypassing the normal
    `create_contact` flow that enforces required contact custom fields)
    — the reception-desk path deliberately accepts partial contacts so
    the staffer doesn't have to fill in every required custom field
    during a walk-in. The operator (or the contact themselves) fills
    them later via the Contacts page.
    """
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
        session.add(contact)
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
    )
    session.add(walk_in)
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


async def checkout(
    session: AsyncSession, *, walk_in_id: uuid.UUID
) -> WalkIn:
    """Stamp `time_out=now()` on a walk-in. Idempotent — if already
    checked out, leaves the existing `time_out` in place."""
    walk_in = ensure_found(await get_walk_in(session, walk_in_id), entity="walk-in")
    if walk_in.time_out is None:
        before = _snapshot(walk_in)
        walk_in.time_out = datetime.now(timezone.utc)
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
    """422 if the target user has no active membership in this org.

    Same join + check as contacts.service / leads.service — keeps the
    cross-tenant guard uniform across reassign endpoints."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
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
        await _assert_user_in_org(
            session, org_id=org_id, user_uuid=assigned_to_id
        )

    before_id = walk_in.assigned_to_id
    if before_id == assigned_to_id:
        return walk_in

    before = _snapshot(walk_in)
    walk_in.assigned_to_id = assigned_to_id
    session.add(
        Activity(
            org_id=org_id,
            entity_type="walk_in",
            entity_id=walk_in.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(
                from_id=before_id, to_id=assigned_to_id, note=note
            ),
            user_id=actor_user_id,
        )
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
) -> int:
    if assigned_to_id is not None:
        await _assert_user_in_org(
            session, org_id=org_id, user_uuid=assigned_to_id
        )

    reassigned = 0
    for wid in ids:
        walk_in = await get_walk_in(session, wid)
        if walk_in is None:
            continue
        if walk_in.assigned_to_id == assigned_to_id:
            continue
        before_id = walk_in.assigned_to_id
        walk_in.assigned_to_id = assigned_to_id
        session.add(
            Activity(
                org_id=org_id,
                entity_type="walk_in",
                entity_id=walk_in.id,
                type=ActivityType.reassign,
                payload=_reassign_payload(
                    from_id=before_id, to_id=assigned_to_id, note=note
                ),
                user_id=actor_user_id,
            )
        )
        reassigned += 1

    await session.commit()
    return reassigned


async def bulk_checkout_walk_ins(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> tuple[int, int]:
    """Bulk equivalent of single-row `checkout`. Per-row processing
    because already-checked-out rows are skipped (not errored) — same
    semantic as the single endpoint. Returns
    `(checked_out, already_checked_out)`."""
    checked_out = 0
    already_out = 0
    now_ts = datetime.now(timezone.utc)
    for wid in ids:
        walk_in = await get_walk_in(session, wid)
        if walk_in is None:
            continue
        if walk_in.org_id != org_id:
            # ORM tenant filter scopes SELECTs but defence-in-depth:
            # skip rows that somehow slipped through.
            continue
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
    """Spin up a `Lead` from a walk-in. Returns (walk_in, contact_id,
    lead_id).

    - 404 if walk-in not found.
    - 409 if walk-in already has `linked_lead_id` (idempotency guard —
      the response embeds the existing lead id so the FE can redirect).
    - 422 if `contact_link_mode='link'` and the `linked_contact_id`
      isn't in the same org.

    Resolves the target contact: `auto` keeps the walk-in's existing
    `contact_id` (quick-register already created/linked it). `link`
    overrides with the explicit contact id, validated tenant-scoped.

    Creates the lead at the first stage of the `leads` pipeline,
    inheriting the walk-in's owner. Source defaults to `manual`
    because `LeadSource` has no `walk_in` enum value — manual is
    accurate (a staffer flipped this).

    Writes an `Activity(type=convert)` on the walk-in's timeline with
    `payload={"contact_id":..., "lead_id":..., "notes":...}`. The
    activity-insert hook then bumps `walk_in.last_activity_at` and
    `lead.last_activity_at` automatically.
    """
    # Imported lazily to avoid a circular import at module load:
    # leads.service imports walk_ins... actually it doesn't, but the
    # pipelines / leads modules pull in chains that are easier to
    # keep deferred from the walk_ins module's import graph.
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
        source=LeadSource.manual,
    )
    lead = await create_lead_service(
        session,
        org_id=org_id,
        payload=lead_payload,
        require_all_required=False,
    )

    walk_in.linked_lead_id = lead.id
    session.add(
        Activity(
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


__all__ = [
    "WalkInStatus",
    "bulk_checkout_walk_ins",
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
]
