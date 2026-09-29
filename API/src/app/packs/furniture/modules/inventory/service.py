"""Service layer for the furniture-pack inventory module.

Three concerns:

1. Warehouses CRUD — straight upsert with `(org_id, name)` unique.
2. Items CRUD — paginated list with warehouse / catalog-category /
   search filters, plus the standard create/update/delete.
3. Movements — `record_movement(item, type, qty, …)` atomically
   updates `qty_on_hand`, inserts the ledger row, and recomputes
   stock alerts.
4. Alerts — `recompute_alerts(item)` opens / closes a row depending on
   `qty_on_hand` vs `reorder_level`. Idempotent.

All mutations route through the caller's `AsyncSession` so the
movement + qty update + alert recompute happen in one transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.catalog.models import CatalogItem
from src.app.packs.furniture.modules.inventory import data_access as _da
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
    InventoryItemFullCreate,
    InventoryItemUpdate,
    WarehouseCreate,
    WarehouseUpdate,
)
from src.app.shared.db.queries import ensure_found
from src.app.shared.storage import get_storage

# --- warehouses ---------------------------------------------------------


async def list_warehouses(session: AsyncSession) -> list[Warehouse]:
    return await _da.list_warehouses_query(session)


async def get_warehouse(session: AsyncSession, warehouse_id: uuid.UUID) -> Warehouse:
    return ensure_found(
        await _da.get_warehouse_by_id(session, warehouse_id),
        entity="warehouse",
    )


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
    _da.insert_warehouse(session, w)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"warehouse '{payload.name}' already exists for this org",
        ) from None
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


async def delete_warehouse(session: AsyncSession, *, warehouse_id: uuid.UUID) -> None:
    w = await get_warehouse(session, warehouse_id)
    await _da.delete_warehouse_row(session, w)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="warehouse still has inventory items — empty it first",
        ) from None


# --- items --------------------------------------------------------------


async def list_items(
    session: AsyncSession,
    *,
    warehouse_id: uuid.UUID | None = None,
    category: str | None = None,
    q: str | None = None,
    active_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[InventoryItem], int]:
    return await _da.list_items_query(
        session,
        warehouse_id=warehouse_id,
        category=category,
        q=q,
        active_only=active_only,
        page=page,
        size=size,
    )


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> InventoryItem:
    return ensure_found(await _da.get_item_by_id(session, item_id), entity="item")


async def hydrate_items_by_ids(
    session: AsyncSession, *, org_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[InventoryItem]:
    """Batch fetch inventory items by id list, scoped to the caller's
    org. Powers the stock-alerts page (and any future consumer) that
    needs to render item context per row without the N-way ``GET
    /items/{item_id}`` fan-out."""
    return await _da.list_items_by_ids_in_org(session, ids=ids, org_id=org_id)


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
        if not await _da.catalog_item_exists_in_org(session, payload.catalog_item_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"catalog_item_id {payload.catalog_item_id} not found",
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
    _da.insert_item(session, item)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"inventory item with sku '{payload.sku}' already exists in this warehouse",
        ) from None
    await session.refresh(item)
    # Open initial alert if reorder_level > 0 and qty_on_hand == 0.
    await recompute_alerts(session, item_id=item.id)
    return item


async def create_item_full(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: InventoryItemFullCreate,
) -> InventoryItem:
    """Atomic create: a catalog row + an inventory row in one
    transaction. Used by the Add Product modal."""
    wh = await get_warehouse(session, payload.warehouse_id)

    catalog = CatalogItem(
        org_id=org_id,
        sku=payload.sku.strip().upper(),
        name=payload.name,
        category=payload.category,
        price=payload.price,
        custom_data=({"description": payload.description} if payload.description else {}),
        is_active=payload.is_active,
    )
    _da.insert_catalog_item(session, catalog)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"catalog SKU '{payload.sku}' already exists for this org",
        ) from None

    inv = InventoryItem(
        org_id=org_id,
        catalog_item_id=catalog.id,
        warehouse_id=wh.id,
        sku=payload.sku.strip().upper(),
        material=payload.material,
        color=payload.color,
        finish=payload.finish,
        dimensions=payload.dimensions,
        reorder_level=payload.reorder_level,
        is_best_seller=payload.is_best_seller,
        is_active=payload.is_active,
    )
    _da.insert_item(session, inv)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"inventory item with SKU '{payload.sku}' already exists in this warehouse"),
        ) from None
    await session.refresh(inv)
    return inv


async def set_item_cover(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    org_id: uuid.UUID,
    file_bytes: bytes,
    content_type: str | None,
    filename: str | None,
) -> str:
    """Persist a cover image for `item_id`, save to storage backend,
    write the served URL to `inventory_items.cover_url`, and return
    that URL."""
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )
    item = await get_item(session, item_id)

    ext = "jpg"
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()[:8]
    storage_path = f"{org_id}/inventory/{item.id}/cover.{ext}"
    ref = await get_storage().put(
        storage_path,
        file_bytes,
        content_type=content_type or "application/octet-stream",
    )

    item.cover_url = ref.url
    await session.commit()
    await session.refresh(item)
    return ref.url


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


async def delete_item(session: AsyncSession, *, item_id: uuid.UUID) -> None:
    item = await get_item(session, item_id)
    await _da.delete_item_row(session, item)
    await session.commit()


# --- movements (the hot path) -------------------------------------------


async def record_movement(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    user_id: uuid.UUID | None,
    type_: MovementType,
    qty: int,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> InventoryMovement:
    """Atomically apply a stock movement."""
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
            detail=(f"insufficient stock: qty_on_hand={item.qty_on_hand}, requested delta={delta}"),
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
    _da.insert_movement(session, movement)
    item.qty_on_hand = new_on_hand
    if type_ == MovementType.receipt:
        item.last_received_at = datetime.now(UTC)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"movement violated DB constraint: {exc.orig}",
        ) from exc
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
    return await _da.list_movements_for_item(session, item_id=item_id, limit=limit)


# --- alerts -------------------------------------------------------------


async def recompute_alerts(session: AsyncSession, *, item_id: uuid.UUID) -> None:
    """Open or close the open alert for `item` so it matches current qty."""
    item = await get_item(session, item_id)

    open_alert = await _da.get_open_alert_for_item(session, item.id)

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
            open_alert.closed_at = datetime.now(UTC)
            await session.commit()
        return

    if open_alert is None:
        _da.insert_alert(
            session,
            StockAlert(
                org_id=item.org_id,
                item_id=item.id,
                severity=desired_severity,
                priority=desired_priority,
                suggested_reorder_qty=suggested,
            ),
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
    severity: AlertSeverity | None = None,
    status_filter: AlertStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[StockAlert], int]:
    return await _da.list_alerts_query(
        session,
        severity=severity,
        status_filter=status_filter,
        page=page,
        size=size,
    )


async def update_alert_status(
    session: AsyncSession,
    *,
    alert_id: uuid.UUID,
    new_status: AlertStatus,
) -> StockAlert:
    alert = ensure_found(await _da.get_alert_by_id(session, alert_id), entity="alert")
    alert.status = new_status
    if new_status == AlertStatus.closed and alert.closed_at is None:
        alert.closed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(alert)
    return alert


__all__ = [
    "create_item",
    "create_item_full",
    "create_warehouse",
    "delete_item",
    "delete_warehouse",
    "get_item",
    "get_warehouse",
    "hydrate_items_by_ids",
    "list_alerts",
    "list_items",
    "list_movements",
    "list_warehouses",
    "record_movement",
    "recompute_alerts",
    "set_item_cover",
    "update_alert_status",
    "update_item",
    "update_warehouse",
]
