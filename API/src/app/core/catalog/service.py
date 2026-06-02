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
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
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
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_CATALOG_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
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
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_CATALOG_ENTITY,
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
