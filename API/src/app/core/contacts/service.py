"""Service layer for the contacts module.

Two responsibilities sit here that the router does not duplicate:

1. **`custom_data` validation**. Every write loads the active org's
   `custom_field_definitions` for `entity_type='contact'` and rejects:
   - keys that are not defined,
   - values whose Python type does not match the declared `field_type`,
   - missing required keys on create (update is partial by design).

2. **Filtered list construction**. The `q`, `source`, `tag`, and dynamic
   `custom.<key>=<value>` filters are translated into SQLAlchemy where
   clauses here so the router stays a thin HTTP shim.

Audit events (`contacts.created`, `.updated`, `.deleted`) fire from
inside each write path.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.models import Contact
from src.app.core.contacts.schemas import ContactCreate, ContactUpdate
from src.app.core.custom_fields.models import CustomFieldDefinition, FieldType


_CONTACT_ENTITY = "contact"


def _snapshot(contact: Contact) -> dict[str, Any]:
    """JSONB-friendly snapshot for audit `before`/`after`."""
    return {
        "id": str(contact.id),
        "full_name": contact.full_name,
        "phone": contact.phone,
        "email": contact.email,
        "source": contact.source,
        "tags": list(contact.tags),
        "notes": contact.notes,
        "custom_data": contact.custom_data,
    }


async def _load_field_defs(session: AsyncSession) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == _CONTACT_ENTITY
        )
    )
    return {row.field_key: row for row in result.scalars()}


def _coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    """Validate / coerce a single `custom_data` value. Raises 422 on mismatch."""
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
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected list of strings",
            )
        return value

    if field_type in (FieldType.number, FieldType.currency):
        # `bool` is a subclass of `int` in Python — reject it explicitly so
        # `True` doesn't sneak past a number check.
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

    # `FieldType` is an exhaustive enum; reaching here means a new type
    # was added without extending this switch. Fail loudly.
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
    """Validate `payload` against defined `contact` custom fields.

    `require_all_required=True` on create; False on partial update.
    Returns a sanitized copy (values coerced where applicable).
    """
    defs = await _load_field_defs(session)

    unknown = set(payload) - set(defs)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "custom_data contains keys not defined for entity "
                f"'contact': {sorted(unknown)}"
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


async def get_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> Contact | None:
    """Return a single contact by id, scoped to the active tenant."""
    result = await session.execute(select(Contact).where(Contact.id == contact_id))
    return result.scalar_one_or_none()


async def create_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: ContactCreate,
) -> Contact:
    cleaned_custom = await _validate_custom_data(
        session, payload=payload.custom_data, require_all_required=True
    )

    contact = Contact(
        org_id=org_id,
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        source=payload.source,
        tags=payload.cleaned_tags(),
        notes=payload.notes,
        custom_data=cleaned_custom,
    )
    session.add(contact)
    await session.commit()
    await session.refresh(contact)

    await audit.log(
        "contacts.created",
        entity_type="contact",
        entity_id=contact.id,
        after=_snapshot(contact),
    )
    return contact


async def update_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    payload: ContactUpdate,
) -> Contact:
    contact = await get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="contact not found"
        )

    before = _snapshot(contact)
    changes = payload.model_dump(exclude_unset=True)

    if "custom_data" in changes:
        changes["custom_data"] = await _validate_custom_data(
            session,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )

    if "tags" in changes and changes["tags"] is not None:
        seen: dict[str, None] = {}
        for tag in changes["tags"]:
            value = str(tag).strip()
            if value and value not in seen:
                seen[value] = None
        changes["tags"] = list(seen)

    for key, value in changes.items():
        setattr(contact, key, value)
    await session.commit()
    await session.refresh(contact)

    await audit.log(
        "contacts.updated",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after=_snapshot(contact),
    )
    return contact


async def delete_contact(
    session: AsyncSession, *, contact_id: uuid.UUID
) -> None:
    contact = await get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="contact not found"
        )
    before = _snapshot(contact)
    contact_uuid = contact.id
    await session.delete(contact)
    await session.commit()

    await audit.log(
        "contacts.deleted",
        entity_type="contact",
        entity_id=contact_uuid,
        before=before,
    )


async def list_contacts(
    session: AsyncSession,
    *,
    q: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
    page: int = 1,
    size: int = 50,
) -> tuple[list[Contact], int]:
    """Paginated list with optional filters. Returns (rows, total).

    - `q` matches full_name / phone / email via ILIKE; trigram GIN index
      accelerates the full_name leg.
    - `source` is exact match.
    - `tag` checks the value is contained in the `tags` array.
    - `custom_filters` is an iterable of `(key, expected_string_value)`
      pairs that translate to `custom_data ->> key = :value`. String
      compare is intentional: it's what the master prompt example uses
      and avoids server-side type guessing.
    """
    filters: list[Any] = []

    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if source:
        filters.append(Contact.source == source)
    if tag:
        filters.append(Contact.tags.contains([tag]))
    for key, value in custom_filters:
        filters.append(Contact.custom_data[key].astext == value)

    where = and_(*filters) if filters else None
    base = select(Contact)
    count_stmt = select(func.count()).select_from(Contact)
    if where is not None:
        base = base.where(where)
        count_stmt = count_stmt.where(where)

    base = base.order_by(Contact.created_at.desc(), Contact.id.desc())
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)
