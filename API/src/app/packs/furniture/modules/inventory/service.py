"""Service layer for the furniture-pack inventory module.

Three concerns:

1. Warehouses CRUD — straight upsert with `(org_id, name)` unique.
2. Items CRUD — paginated list with warehouse / catalog-category /
   search filters, plus the standard create/update/delete.
3. Movements — `record_movement(item, type, qty, …)` atomically
   updates `qty_on_hand`, inserts the ledger row, and recomputes
   stock alerts. Sign rules:
     - receipt   : qty positive, on_hand += qty
     - dispatch  : qty positive, on_hand -= qty  (rejected if negative)
     - transfer  : qty positive, on_hand -= qty  (caller pairs with a receipt elsewhere)
     - adjust    : qty signed (positive or negative), on_hand += qty
4. Alerts — `recompute_alerts(item)` opens / closes a row depending on
   `qty_on_hand` vs `reorder_level`. Idempotent: if an alert already
   matches the current state we don't churn it.

All mutations route through the caller's `AsyncSession` so the
movement + qty update + alert recompute happen in one transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.catalog.models import CatalogItem
from src.app.packs.furniture.modules.inventory.models import (
    AlertPriority,
    AlertSeverity,
    AlertStatus,
    InventoryItem,
    InventoryMovement,
    MovementType,
    StockAlert,
    Warehouse,
)
from src.app.packs.furniture.modules.inventory.schemas import (
    InventoryItemCreate,
    InventoryItemUpdate,
    WarehouseCreate,
    WarehouseUpdate,
)
from src.app.shared.db.queries import get_or_404


# --- warehouses ---------------------------------------------------------


async def list_warehouses(session: AsyncSession) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(
        Warehouse.is_default.desc(), Warehouse.name.asc()
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_warehouse(
    session: AsyncSession, warehouse_id: uuid.UUID
) -> Warehouse:
    return await get_or_404(session, Warehouse, warehouse_id, entity="warehouse")


async def create_warehouse(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: WarehouseCreate,
) -> Warehouse:
    w = Warehouse(
        org_id=org_id,
        name=payload.name,
        address=payload.address,
        contact_phone=payload.contact_phone,
        is_default=payload.is_default,
    )
    session.add(w)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"warehouse '{payload.name}' already exists for this org",
        )
    await session.refresh(w)
    await audit.log(
        "inventory.warehouse_created",
        entity_type="warehouse",
        entity_id=w.id,
        after={"name": w.name, "is_default": w.is_default},
    )
    return w


async def update_warehouse(
    session: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    payload: WarehouseUpdate,
) -> Warehouse:
    w = await get_warehouse(session, warehouse_id)
    changed = False
    if payload.name is not None:
        w.name = payload.name
        changed = True
    if payload.address is not None:
        w.address = payload.address
        changed = True
    if payload.contact_phone is not None:
        w.contact_phone = payload.contact_phone
        changed = True
    if payload.is_default is not None:
        w.is_default = payload.is_default
        changed = True
    if changed:
        await session.commit()
        await session.refresh(w)
    return w


async def delete_warehouse(
    session: AsyncSession, *, warehouse_id: uuid.UUID
) -> None:
    w = await get_warehouse(session, warehouse_id)
    await session.delete(w)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="warehouse still has inventory items — empty it first",
        )


# --- items --------------------------------------------------------------


async def list_items(
    session: AsyncSession,
    *,
    warehouse_id: Optional[uuid.UUID] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[InventoryItem], int]:
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
    rows = (
        (await session.execute(base.offset(offset).limit(size)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_item(
    session: AsyncSession, item_id: uuid.UUID
) -> InventoryItem:
    return await get_or_404(session, InventoryItem, item_id, entity="item")


async def create_item(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: InventoryItemCreate,
) -> InventoryItem:
    # Validate FK targets are in scope (RLS would block out-of-org IDs
    # but a 404 is friendlier than a generic 500).
    await get_warehouse(session, payload.warehouse_id)
    if payload.catalog_item_id is not None:
        await get_or_404(
            session, CatalogItem, payload.catalog_item_id, entity="catalog_item_id"
        )

    item = InventoryItem(
        org_id=org_id,
        catalog_item_id=payload.catalog_item_id,
        warehouse_id=payload.warehouse_id,
        sku=payload.sku,
        material=payload.material,
        color=payload.color,
        finish=payload.finish,
        dimensions=payload.dimensions,
        reorder_level=payload.reorder_level,
        custom_data=payload.custom_data,
        is_best_seller=payload.is_best_seller,
        is_active=payload.is_active,
    )
    session.add(item)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"inventory item with sku '{payload.sku}' already exists in this warehouse",
        )
    await session.refresh(item)
    # Open initial alert if reorder_level > 0 and qty_on_hand == 0.
    await recompute_alerts(session, item_id=item.id)
    return item


async def update_item(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
) -> InventoryItem:
    item = await get_item(session, item_id)
    changed = False
    if payload.catalog_item_id is not None:
        item.catalog_item_id = payload.catalog_item_id
        changed = True
    if payload.warehouse_id is not None:
        item.warehouse_id = payload.warehouse_id
        changed = True
    if payload.material is not None:
        item.material = payload.material
        changed = True
    if payload.color is not None:
        item.color = payload.color
        changed = True
    if payload.finish is not None:
        item.finish = payload.finish
        changed = True
    if payload.dimensions is not None:
        item.dimensions = payload.dimensions
        changed = True
    if payload.reorder_level is not None:
        item.reorder_level = payload.reorder_level
        changed = True
    if payload.custom_data is not None:
        item.custom_data = payload.custom_data
        changed = True
    if payload.is_best_seller is not None:
        item.is_best_seller = payload.is_best_seller
        changed = True
    if payload.is_active is not None:
        item.is_active = payload.is_active
        changed = True
    if changed:
        await session.commit()
        await session.refresh(item)
        # Reorder threshold may have changed — re-evaluate alerts.
        if payload.reorder_level is not None:
            await recompute_alerts(session, item_id=item.id)
    return item


async def delete_item(
    session: AsyncSession, *, item_id: uuid.UUID
) -> None:
    item = await get_item(session, item_id)
    await session.delete(item)
    await session.commit()


# --- movements (the hot path) -------------------------------------------


async def record_movement(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID | None,
    type_: MovementType,
    qty: int,
    reference_type: Optional[str] = None,
    reference_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> InventoryMovement:
    """Atomically apply a stock movement.

    Sign of `qty` is derived from `type_`:
      receipt   →  +qty   (must be positive)
      dispatch  →  -qty   (must be positive; rejects negative on_hand)
      transfer  →  -qty   (must be positive; caller pairs with a receipt)
      adjust    →  +qty as supplied (caller passes signed delta)

    Persists a `InventoryMovement` row, updates `InventoryItem.qty_on_hand`
    and `last_received_at`, then runs `recompute_alerts`. Failure to
    satisfy the qty_on_hand >= 0 CHECK constraint is translated to 400.
    """
    item = await get_item(session, item_id)

    if type_ in (MovementType.receipt, MovementType.dispatch, MovementType.transfer):
        if qty <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{type_.value} qty must be positive",
            )
        delta = qty if type_ == MovementType.receipt else -qty
    elif type_ == MovementType.adjust:
        if qty == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="adjust qty must be non-zero",
            )
        delta = qty
    else:  # pragma: no cover — exhaustive
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown movement type {type_!r}",
        )

    new_on_hand = item.qty_on_hand + delta
    if new_on_hand < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"insufficient stock: qty_on_hand={item.qty_on_hand}, "
                f"requested delta={delta}"
            ),
        )

    movement = InventoryMovement(
        org_id=item.org_id,
        item_id=item.id,
        type=type_,
        qty=delta,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=notes,
        user_id=user_id,
    )
    session.add(movement)
    item.qty_on_hand = new_on_hand
    if type_ == MovementType.receipt:
        item.last_received_at = datetime.now(timezone.utc)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"movement violated DB constraint: {exc.orig}",
        )
    await session.refresh(movement)
    await session.refresh(item)

    await audit.log(
        "inventory.movement_recorded",
        entity_type="inventory_item",
        entity_id=item.id,
        after={
            "type": type_.value,
            "delta": delta,
            "qty_on_hand": item.qty_on_hand,
            "reference_type": reference_type,
        },
    )

    await recompute_alerts(session, item_id=item.id)
    return movement


async def list_movements(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    limit: int = 100,
) -> list[InventoryMovement]:
    stmt = (
        select(InventoryMovement)
        .where(InventoryMovement.item_id == item_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# --- alerts -------------------------------------------------------------


async def recompute_alerts(
    session: AsyncSession, *, item_id: uuid.UUID
) -> None:
    """Open or close the open alert for `item` so it matches current qty.

    Logic:
      qty_on_hand == 0     and reorder_level > 0  → alert(severity=out,  priority=high)
      qty_on_hand <= rl    and rl > 0             → alert(severity=low,  priority=med)
      otherwise                                    → close any open alert
    """
    item = await get_item(session, item_id)

    open_alert = (
        await session.execute(
            select(StockAlert)
            .where(StockAlert.item_id == item.id)
            .where(StockAlert.status == AlertStatus.open)
            .limit(1)
        )
    ).scalar_one_or_none()

    desired_severity: AlertSeverity | None
    desired_priority: AlertPriority
    if item.reorder_level <= 0:
        desired_severity = None
        desired_priority = AlertPriority.med
    elif item.qty_on_hand <= 0:
        desired_severity = AlertSeverity.out
        desired_priority = AlertPriority.high
    elif item.qty_on_hand <= item.reorder_level:
        desired_severity = AlertSeverity.low
        desired_priority = AlertPriority.med
    else:
        desired_severity = None
        desired_priority = AlertPriority.med

    suggested = max(item.reorder_level * 2 - item.qty_on_hand, 0)

    if desired_severity is None:
        # Stock is healthy → close any open alert.
        if open_alert is not None:
            open_alert.status = AlertStatus.closed
            open_alert.closed_at = datetime.now(timezone.utc)
            await session.commit()
        return

    if open_alert is None:
        session.add(
            StockAlert(
                org_id=item.org_id,
                item_id=item.id,
                severity=desired_severity,
                priority=desired_priority,
                suggested_reorder_qty=suggested,
            )
        )
        await session.commit()
        return

    # Open alert exists — only mutate it if severity/priority/qty
    # changed so we don't churn updated_at unnecessarily.
    changed = False
    if open_alert.severity != desired_severity:
        open_alert.severity = desired_severity
        changed = True
    if open_alert.priority != desired_priority:
        open_alert.priority = desired_priority
        changed = True
    if open_alert.suggested_reorder_qty != suggested:
        open_alert.suggested_reorder_qty = suggested
        changed = True
    if changed:
        await session.commit()


async def list_alerts(
    session: AsyncSession,
    *,
    severity: Optional[AlertSeverity] = None,
    status_filter: Optional[AlertStatus] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[StockAlert], int]:
    filters: list[Any] = []
    if severity is not None:
        filters.append(StockAlert.severity == severity)
    if status_filter is not None:
        filters.append(StockAlert.status == status_filter)
    where = and_(*filters) if filters else None

    base = select(StockAlert)
    if where is not None:
        base = base.where(where)
    base = base.order_by(
        StockAlert.priority.desc(), StockAlert.created_at.desc()
    )

    total_stmt = select(func.count()).select_from(StockAlert)
    if where is not None:
        total_stmt = total_stmt.where(where)
    total = (await session.execute(total_stmt)).scalar_one()

    offset = (page - 1) * size
    rows = (
        (await session.execute(base.offset(offset).limit(size)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def update_alert_status(
    session: AsyncSession,
    *,
    alert_id: uuid.UUID,
    new_status: AlertStatus,
) -> StockAlert:
    alert = await get_or_404(session, StockAlert, alert_id, entity="alert")
    alert.status = new_status
    if new_status == AlertStatus.closed and alert.closed_at is None:
        alert.closed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(alert)
    return alert


__all__ = [
    "create_item",
    "create_warehouse",
    "delete_item",
    "delete_warehouse",
    "get_item",
    "get_warehouse",
    "list_alerts",
    "list_items",
    "list_movements",
    "list_warehouses",
    "record_movement",
    "recompute_alerts",
    "update_alert_status",
    "update_item",
    "update_warehouse",
]
