"""Data-access layer for the furniture-pack inventory module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Warehouses (``fp_warehouses``)
      get_warehouse_by_id, list_warehouses_query,
      insert_warehouse, delete_warehouse_row
  * Inventory items (``fp_inventory_items``)
      get_item_by_id, list_items_query,
      insert_item, delete_item_row
  * Inventory movements (``fp_inventory_movements``)
      list_movements_for_item, insert_movement
  * Stock alerts (``fp_stock_alerts``)
      get_open_alert_for_item, list_alerts_query,
      get_alert_by_id, insert_alert
  * Cross-module (against ``catalog_items``)
      catalog_item_exists_in_org, insert_catalog_item
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog.models import CatalogItem
from src.app.packs.furniture.modules.inventory.models import (
    AlertSeverity,
    AlertStatus,
    InventoryItem,
    InventoryMovement,
    StockAlert,
    Warehouse,
)

# --- Warehouses ---------------------------------------------------------


async def get_warehouse_by_id(session: AsyncSession, warehouse_id: uuid.UUID) -> Warehouse | None:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(select(Warehouse).where(Warehouse.id == warehouse_id))
    ).scalar_one_or_none()


async def list_warehouses_query(session: AsyncSession) -> list[Warehouse]:
    """All warehouses for the active tenant, default first, then
    alphabetical by name."""
    stmt = select(Warehouse).order_by(Warehouse.is_default.desc(), Warehouse.name.asc())
    return list((await session.execute(stmt)).scalars().all())


def insert_warehouse(session: AsyncSession, warehouse: Warehouse) -> None:
    """Register an already-constructed Warehouse for INSERT."""
    session.add(warehouse)


async def delete_warehouse_row(session: AsyncSession, warehouse: Warehouse) -> None:
    """Mark a Warehouse row for DELETE. Caller commits."""
    await session.delete(warehouse)


# --- Inventory items ----------------------------------------------------


async def get_item_by_id(session: AsyncSession, item_id: uuid.UUID) -> InventoryItem | None:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(select(InventoryItem).where(InventoryItem.id == item_id))
    ).scalar_one_or_none()


async def list_items_query(
    session: AsyncSession,
    *,
    warehouse_id: uuid.UUID | None = None,
    category: str | None = None,
    q: str | None = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[InventoryItem], int]:
    """Filtered paginated list of inventory items, ordered by SKU.

    ``category`` / ``q`` trigger a LEFT-OUTER JOIN to ``catalog_items``
    so the filters can match against catalog fields (category, name)
    while still including inventory rows whose catalog link is NULL.
    """
    filters: list[Any] = []
    if warehouse_id is not None:
        filters.append(InventoryItem.warehouse_id == warehouse_id)
    if active_only:
        filters.append(InventoryItem.is_active.is_(True))

    base = select(InventoryItem)
    total_base = select(func.count()).select_from(InventoryItem)

    if category is not None or q is not None:
        base = base.join(
            CatalogItem,
            CatalogItem.id == InventoryItem.catalog_item_id,
            isouter=True,
        )
        total_base = total_base.join(
            CatalogItem,
            CatalogItem.id == InventoryItem.catalog_item_id,
            isouter=True,
        )
        if category is not None:
            filters.append(CatalogItem.category == category)
        if q is not None:
            like = f"%{q}%"
            filters.append(
                or_(
                    InventoryItem.sku.ilike(like),
                    CatalogItem.name.ilike(like),
                )
            )

    where = and_(*filters) if filters else None
    if where is not None:
        base = base.where(where)
        total_base = total_base.where(where)
    base = base.order_by(InventoryItem.sku.asc())

    total = (await session.execute(total_base)).scalar_one()
    offset = (page - 1) * size
    rows = (await session.execute(base.offset(offset).limit(size))).scalars().all()
    return list(rows), int(total)


def insert_item(session: AsyncSession, item: InventoryItem) -> None:
    """Register an already-constructed InventoryItem for INSERT."""
    session.add(item)


async def delete_item_row(session: AsyncSession, item: InventoryItem) -> None:
    """Mark an InventoryItem row for DELETE. Caller commits."""
    await session.delete(item)


# --- Inventory movements ------------------------------------------------


async def list_movements_for_item(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    limit: int = 100,
) -> list[InventoryMovement]:
    """All movements for one item, newest first."""
    stmt = (
        select(InventoryMovement)
        .where(InventoryMovement.item_id == item_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def insert_movement(session: AsyncSession, movement: InventoryMovement) -> None:
    """Register an already-constructed InventoryMovement for INSERT."""
    session.add(movement)


# --- Stock alerts -------------------------------------------------------


async def get_open_alert_for_item(session: AsyncSession, item_id: uuid.UUID) -> StockAlert | None:
    """The single open alert for an item (if any). Used by the
    ``recompute_alerts`` decision tree to avoid churning the row when
    the desired state matches the current state."""
    return (
        await session.execute(
            select(StockAlert)
            .where(StockAlert.item_id == item_id)
            .where(StockAlert.status == AlertStatus.open)
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_alert_by_id(session: AsyncSession, alert_id: uuid.UUID) -> StockAlert | None:
    """Single-row alert read by PK."""
    return (
        await session.execute(select(StockAlert).where(StockAlert.id == alert_id))
    ).scalar_one_or_none()


async def list_alerts_query(
    session: AsyncSession,
    *,
    severity: AlertSeverity | None = None,
    status_filter: AlertStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[StockAlert], int]:
    """Filtered paginated list of stock alerts. Default order is
    priority desc then newest first — high-priority alerts surface
    at the top of the Stock Alerts tab."""
    filters: list[Any] = []
    if severity is not None:
        filters.append(StockAlert.severity == severity)
    if status_filter is not None:
        filters.append(StockAlert.status == status_filter)
    where = and_(*filters) if filters else None

    base = select(StockAlert)
    if where is not None:
        base = base.where(where)
    base = base.order_by(StockAlert.priority.desc(), StockAlert.created_at.desc())

    total_stmt = select(func.count()).select_from(StockAlert)
    if where is not None:
        total_stmt = total_stmt.where(where)
    total = (await session.execute(total_stmt)).scalar_one()

    offset = (page - 1) * size
    rows = (await session.execute(base.offset(offset).limit(size))).scalars().all()
    return list(rows), int(total)


def insert_alert(session: AsyncSession, alert: StockAlert) -> None:
    """Register an already-constructed StockAlert for INSERT."""
    session.add(alert)


# --- Cross-module (catalog_items) ---------------------------------------


async def catalog_item_exists_in_org(session: AsyncSession, catalog_item_id: uuid.UUID) -> bool:
    """Narrow-column existence check against ``catalog_items``. Used
    by the inventory-item-create validator to reject out-of-org
    catalog_item_id references with a friendly 422."""
    row = (
        await session.execute(select(CatalogItem.id).where(CatalogItem.id == catalog_item_id))
    ).scalar_one_or_none()
    return row is not None


def insert_catalog_item(session: AsyncSession, catalog_item: CatalogItem) -> None:
    """Register an already-constructed CatalogItem for INSERT. Used
    by ``create_item_full`` to land the catalog row + the inventory
    row in one transaction."""
    session.add(catalog_item)


__all__ = [
    "catalog_item_exists_in_org",
    "delete_item_row",
    "delete_warehouse_row",
    "get_alert_by_id",
    "get_item_by_id",
    "get_open_alert_for_item",
    "get_warehouse_by_id",
    "insert_alert",
    "insert_catalog_item",
    "insert_item",
    "insert_movement",
    "insert_warehouse",
    "list_alerts_query",
    "list_items_query",
    "list_movements_for_item",
    "list_warehouses_query",
]
