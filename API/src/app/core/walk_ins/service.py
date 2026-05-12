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
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.core.walk_ins.schemas import (
    QuickRegisterPayload,
    WalkInCreate,
    WalkInUpdate,
)


_WALK_IN_ENTITY = "walk_in"


def _snapshot(w: WalkIn) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "contact_id": str(w.contact_id),
        "time_in": w.time_in.isoformat(),
        "time_out": w.time_out.isoformat() if w.time_out is not None else None,
        "requirement": w.requirement,
        "budget": str(w.budget) if w.budget is not None else None,
        "assigned_to_id": (
            str(w.assigned_to_id) if w.assigned_to_id is not None else None
        ),
        "status": w.status.value,
        "notes": w.notes,
        "custom_data": w.custom_data,
    }


# --- custom_data validation (mirrors contacts / leads / appointments) ---


async def _load_field_defs(
    session: AsyncSession,
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == _WALK_IN_ENTITY
        )
    )
    return {row.field_key: row for row in result.scalars()}


def _coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    if value is None:
        return None
    if field_type in (FieldType.text, FieldType.phone, FieldType.email, FieldType.select):
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected string",
            )
        return value
    if field_type is FieldType.multiselect:
        if not isinstance(value, list) or not all(
            isinstance(v, str) for v in value
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected list of strings",
            )
        return value
    if field_type in (FieldType.number, FieldType.currency):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected number",
            )
        return value
    if field_type is FieldType.boolean:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected boolean",
            )
        return value
    if field_type is FieldType.date:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO date string",
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO date",
            ) from exc
        return value
    if field_type is FieldType.datetime:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO datetime string",
            )
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO datetime",
            ) from exc
        return value
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled field_type {field_type!r}",
    )


async def _validate_custom_data(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    require_all_required: bool,
) -> dict[str, Any]:
    defs = await _load_field_defs(session)

    unknown = set(payload) - set(defs)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "custom_data contains keys not defined for entity "
                f"'walk_in': {sorted(unknown)}"
            ),
        )

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        cleaned[key] = _coerce_value(defs[key].field_type, key, value)

    if require_all_required:
        missing = [
            key
            for key, defn in defs.items()
            if defn.is_required and (key not in cleaned or cleaned[key] is None)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data missing required keys: {sorted(missing)}",
            )
    return cleaned


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
    return (
        await session.execute(
            select(Contact).where(Contact.phone == normalized)
        )
    ).scalar_one_or_none()


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
    cleaned_custom = await _validate_custom_data(
        session, payload=payload.custom_data, require_all_required=True
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

    await audit.log(
        "walk_ins.created",
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
    walk_in = await get_walk_in(session, walk_in_id)
    if walk_in is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found"
        )

    before = _snapshot(walk_in)
    changes = payload.model_dump(exclude_unset=True)
    if "custom_data" in changes:
        changes["custom_data"] = await _validate_custom_data(
            session,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    for key, value in changes.items():
        setattr(walk_in, key, value)
    await session.commit()
    await session.refresh(walk_in)

    await audit.log(
        "walk_ins.updated",
        entity_type="walk_in",
        entity_id=walk_in.id,
        before=before,
        after=_snapshot(walk_in),
    )
    return walk_in


async def delete_walk_in(session: AsyncSession, *, walk_in_id: uuid.UUID) -> None:
    walk_in = await get_walk_in(session, walk_in_id)
    if walk_in is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found"
        )
    before = _snapshot(walk_in)
    walk_in_uuid = walk_in.id
    await session.delete(walk_in)
    await session.commit()

    await audit.log(
        "walk_ins.deleted",
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
    page: int = 1,
    size: int = 50,
) -> tuple[list[WalkIn], int]:
    """Paginated list. `open_only=True` filters to rows with no
    `time_out` (currently in-store)."""
    filters: list[Any] = []
    if status_filter is not None:
        filters.append(WalkIn.status == status_filter)
    if assigned_to is not None:
        filters.append(WalkIn.assigned_to_id == assigned_to)
    if open_only:
        filters.append(WalkIn.time_out.is_(None))

    where = and_(*filters) if filters else None

    base = select(WalkIn)
    count_stmt = select(func.count()).select_from(WalkIn)
    if where is not None:
        base = base.where(where)
        count_stmt = count_stmt.where(where)
    base = base.order_by(WalkIn.time_in.desc(), WalkIn.id.desc())

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


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
    cleaned_custom = await _validate_custom_data(
        session, payload=payload.custom_data, require_all_required=True
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
    walk_in = await get_walk_in(session, walk_in_id)
    if walk_in is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found"
        )
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


__all__ = [
    "WalkInStatus",
    "checkout",
    "create_walk_in",
    "delete_walk_in",
    "get_walk_in",
    "list_walk_ins",
    "quick_register",
    "update_walk_in",
]
