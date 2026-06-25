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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog import data_access as _da
from src.app.core.catalog.models import CatalogItem
from src.app.core.catalog.schemas import (
    CatalogItemCreate,
    CatalogItemUpdate,
)
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found
from src.app.shared.files import (
    ImageValidationError,
    validate_image_upload,
)
from src.app.shared.storage import get_storage


_CATALOG_ENTITY = "catalog_item"


_SNAPSHOT_FIELDS = (
    "id",
    "sku",
    "name",
    "category",
    "price",
    "currency",
    "is_active",
    "image_url",
    "custom_data",
)


def _snapshot(item: CatalogItem) -> dict[str, Any]:
    return snapshot(item, fields=_SNAPSHOT_FIELDS)


# --- CRUD ---


async def get_item(
    session: AsyncSession, item_id: uuid.UUID
) -> Optional[CatalogItem]:
    return await _da.get_catalog_item_by_id(session, item_id)


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
    _da.insert_catalog_item(session, item)
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
    await _da.delete_catalog_item_row(session, item)
    await session.commit()

    await log_entity_change(
        action="catalog.deleted",
        entity_type="catalog_item",
        entity_id=item_uuid,
        before=before,
    )


async def set_item_image(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    file_bytes: bytes,
) -> CatalogItem:
    """Validate + persist an uploaded image for `item_id`.

    libmagic sniffs the real MIME from the bytes (filename ignored),
    storage path is tenant-scoped `catalog/{org_id}/{item_id}.{ext}`,
    and the resulting public URL lands on `image_url`. A re-upload
    overwrites the file at the same path; the URL only changes if
    the detected extension changes (e.g. JPEG → PNG).
    """
    item = ensure_found(await get_item(session, item_id), entity="catalog item")

    try:
        mime, ext = validate_image_upload(file_bytes)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    storage = get_storage()
    storage_path = f"catalog/{org_id}/{item_id}.{ext}"
    ref = storage.put(storage_path, file_bytes, content_type=mime)

    before = _snapshot(item)
    item.image_url = ref.url
    await session.commit()
    await session.refresh(item)

    await log_entity_change(
        action="catalog.image_uploaded",
        entity_type="catalog_item",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    return item


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
    return await _da.list_catalog_items_query(
        session,
        q=q,
        category=category,
        active_only=active_only,
        page=page,
        size=size,
    )


__all__ = [
    "create_item",
    "delete_item",
    "get_item",
    "list_items",
    "set_item_image",
    "update_item",
]
