"""Data-access layer for the catalog module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations:

  * ``get_catalog_item_by_id`` — single-row read by PK.
  * ``list_catalog_items_query`` — paginated filterable list with ``q``
    (ILIKE across name + sku), exact-match category, optional
    active-only + status filters; ordered by name then sku for stable
    autocomplete results.
  * ``count_catalog_items_by_status`` — one-round-trip status histogram
    for the owner-dashboard tab bar.
  * ``list_published_items`` — public grid loader (skips the standard
    filter set — the caller passes only ``org_id``).
  * ``insert_catalog_item`` / ``delete_catalog_item_row`` — caller
    commits, caller catches IntegrityError on the ``(org_id, sku)``
    uniqueness violation.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog.constants import CatalogStatus
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
    category_id: uuid.UUID | None = None,
    active_only: bool = False,
    statuses: list[str] | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[CatalogItem], int]:
    """Paginated filtered list. ``q`` ILIKEs across name + sku — the
    autocomplete picker uses this same shape."""
    filters: list[Any] = []
    if q:
        like = f"%{q}%"
        filters.append(or_(CatalogItem.name.ilike(like), CatalogItem.sku.ilike(like)))
    if category_id is not None:
        # New shape wins when both are supplied.
        filters.append(CatalogItem.category_id == category_id)
    elif category:
        # Back-compat free-text match (category_id-less callers).
        filters.append(CatalogItem.category == category)
    if active_only:
        filters.append(CatalogItem.is_active.is_(True))
    if statuses:
        filters.append(CatalogItem.status.in_(statuses))

    base = select(CatalogItem)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(CatalogItem.name.asc(), CatalogItem.sku.asc())
    return await paginate(session, base, page=page, size=size)


async def count_catalog_items_by_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict[str, int]:
    """One-round-trip status histogram for the owner-dashboard tabs.

    Returns a dict keyed by every status the org currently has rows
    for; the caller merges with the full ``CatalogStatus`` enum to
    render zeros for empty tabs."""
    stmt = (
        select(CatalogItem.status, func.count(CatalogItem.id))
        .where(CatalogItem.org_id == org_id)
        .group_by(CatalogItem.status)
    )
    rows = (await session.execute(stmt)).all()
    return {row[0]: int(row[1]) for row in rows}


async def list_published_items(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 200,
) -> list[CatalogItem]:
    """Public grid loader — every ``published`` catalog item for one
    org, ordered by ``published_at`` descending (freshest first).

    Deliberately narrow: no ``q`` / ``category`` / ``active_only``
    filters. The public grid is a customer-facing showcase, not the
    owner's admin table."""
    stmt = (
        select(CatalogItem)
        .where(
            CatalogItem.org_id == org_id,
            CatalogItem.status == CatalogStatus.published.value,
        )
        .order_by(CatalogItem.published_at.desc().nulls_last(), CatalogItem.name.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def insert_catalog_item(session: AsyncSession, item: CatalogItem) -> None:
    """Register an already-constructed CatalogItem for INSERT."""
    session.add(item)


async def delete_catalog_item_row(session: AsyncSession, item: CatalogItem) -> None:
    """Mark a CatalogItem row for DELETE."""
    await session.delete(item)


__all__ = [
    "count_catalog_items_by_status",
    "delete_catalog_item_row",
    "get_catalog_item_by_id",
    "insert_catalog_item",
    "list_catalog_items_query",
    "list_published_items",
]
