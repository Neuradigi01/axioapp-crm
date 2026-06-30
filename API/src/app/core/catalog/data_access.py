"""Data-access layer for the catalog module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Four operations cover the module's needs:

  * ``get_catalog_item_by_id`` — single-row read by PK.
  * ``list_catalog_items_query`` — paginated filterable list with ``q``
    (ILIKE across name + sku), exact-match category, optional
    active-only filter; ordered by name then sku for stable
    autocomplete results.
  * ``insert_catalog_item`` / ``delete_catalog_item_row`` — caller
    commits, caller catches IntegrityError on the ``(org_id, sku)``
    uniqueness violation.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog.models import CatalogItem
from src.app.shared.db.pagination import paginate


async def get_catalog_item_by_id(session: AsyncSession, item_id: uuid.UUID) -> CatalogItem | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(CatalogItem).where(CatalogItem.id == item_id))
    return result.scalar_one_or_none()


async def list_catalog_items_query(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CatalogItem], int]:
    """Paginated filtered list. ``q`` ILIKEs across name + sku — the
    autocomplete picker uses this same shape."""
    filters: list[Any] = []
    if q:
        like = f"%{q}%"
        filters.append(or_(CatalogItem.name.ilike(like), CatalogItem.sku.ilike(like)))
    if category:
        filters.append(CatalogItem.category == category)
    if active_only:
        filters.append(CatalogItem.is_active.is_(True))

    base = select(CatalogItem)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(CatalogItem.name.asc(), CatalogItem.sku.asc())
    return await paginate(session, base, page=page, size=size)


def insert_catalog_item(session: AsyncSession, item: CatalogItem) -> None:
    """Register an already-constructed CatalogItem for INSERT."""
    session.add(item)


async def delete_catalog_item_row(session: AsyncSession, item: CatalogItem) -> None:
    """Mark a CatalogItem row for DELETE."""
    await session.delete(item)


__all__ = [
    "delete_catalog_item_row",
    "get_catalog_item_by_id",
    "insert_catalog_item",
    "list_catalog_items_query",
]
