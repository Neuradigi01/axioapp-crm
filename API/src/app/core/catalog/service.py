"""Service layer for the catalog module.

Same `custom_data` validation engine as contacts / leads / appointments
— entity_type `catalog_item`. Filtered list supports:

  - `q`     — ILIKE across name + sku (autocomplete picker uses this)
  - `category` — exact match
  - `active_only` — drops `is_active=false` rows

A duplicate `(org_id, sku)` violates the unique constraint at the DB
level; we catch the IntegrityError and surface a 409 with a friendly
message rather than letting the raw DB error escape.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.catalog.models import CatalogItem
from src.app.core.catalog.schemas import (
    CatalogItemCreate,
    CatalogItemUpdate,
)
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import ensure_found


_CATALOG_ENTITY = "catalog_item"


_SNAPSHOT_FIELDS = (
    "id",
    "sku",
    "name",
    "category",
    "price",
    "currency",
    "is_active",
    "custom_data",
)


def _snapshot(item: CatalogItem) -> dict[str, Any]:
    return snapshot(item, fields=_SNAPSHOT_FIELDS)


# --- custom_data validation (same engine as contacts/leads/appointments) ---


async def _load_field_defs(
    session: AsyncSession,
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == _CATALOG_ENTITY
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
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
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
                f"'catalog_item': {sorted(unknown)}"
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


# --- CRUD ---


async def get_item(
    session: AsyncSession, item_id: uuid.UUID
) -> Optional[CatalogItem]:
    result = await session.execute(
        select(CatalogItem).where(CatalogItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def create_item(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: CatalogItemCreate,
) -> CatalogItem:
    cleaned_custom = await _validate_custom_data(
        session, payload=payload.custom_data, require_all_required=True
    )
    item = CatalogItem(
        org_id=org_id,
        sku=payload.sku,
        name=payload.name,
        category=payload.category,
        price=payload.price,
        currency=payload.currency,
        is_active=payload.is_active,
        custom_data=cleaned_custom,
    )
    session.add(item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SKU {payload.sku!r} already exists in this org",
        ) from exc
    await session.refresh(item)

    await log_entity_change(
        action="catalog.created",
        entity_type="catalog_item",
        entity_id=item.id,
        after=_snapshot(item),
    )
    return item


async def update_item(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
) -> CatalogItem:
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    before = _snapshot(item)
    changes = payload.model_dump(exclude_unset=True)
    if "custom_data" in changes:
        changes["custom_data"] = await _validate_custom_data(
            session,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    for key, value in changes.items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)

    await log_entity_change(
        action="catalog.updated",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item


async def delete_item(session: AsyncSession, *, item_id: uuid.UUID) -> None:
    item = ensure_found(await get_item(session, item_id), entity="catalog item")
    before = _snapshot(item)
    item_uuid = item.id
    await session.delete(item)
    await session.commit()

    await log_entity_change(
        action="catalog.deleted",
        entity_type="catalog_item",
        entity_id=item_uuid,
        before=before,
    )


async def list_items(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    category: Optional[str] = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CatalogItem], int]:
    """Paginated filtered list. `q` ILIKEs across name + sku."""
    filters: list[Any] = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(CatalogItem.name.ilike(like), CatalogItem.sku.ilike(like))
        )
    if category:
        filters.append(CatalogItem.category == category)
    if active_only:
        filters.append(CatalogItem.is_active.is_(True))

    where = and_(*filters) if filters else None
    base = select(CatalogItem)
    if where is not None:
        base = base.where(where)
    base = base.order_by(CatalogItem.name.asc(), CatalogItem.sku.asc())

    return await paginate(session, base, page=page, size=size)


__all__ = [
    "create_item",
    "delete_item",
    "get_item",
    "list_items",
    "update_item",
]
