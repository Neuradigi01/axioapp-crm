"""HTTP routes for the furniture-pack inventory module.

  /api/v1/inventory/warehouses                  (CRUD)
  /api/v1/inventory/items                       (CRUD + filters)
  /api/v1/inventory/items/{id}/movements        (GET list, POST record)
  /api/v1/inventory/alerts                      (GET list, PATCH status)

Permissions:
  - `inventory.read`     → all GETs
  - `inventory.write`    → warehouse CRUD, item CRUD, receipt/adjust movements
  - `inventory.dispatch` → `type='dispatch'` movements
  - `inventory.transfer` → `type='transfer'` movements
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.catalog.models import CatalogItem
from src.app.core.users.models import User
from src.app.packs.furniture.modules.inventory.models import (
    AlertSeverity,
    AlertStatus,
    InventoryItem,
    MovementType,
)
from src.app.packs.furniture.modules.inventory.schemas import (
    CoverUploadResponse,
    InventoryItemCreate,
    InventoryItemFullCreate,
    InventoryItemListResponse,
    InventoryItemOut,
    InventoryItemUpdate,
    MovementCreate,
    MovementOut,
    StockAlertOut,
    StockAlertPatch,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)
from src.app.shared.storage import get_storage
from src.app.packs.furniture.modules.inventory.service import (
    create_item,
    create_warehouse,
    delete_item,
    delete_warehouse,
    get_item,
    get_warehouse,
    list_alerts,
    list_items,
    list_movements,
    list_warehouses,
    record_movement,
    update_alert_status,
    update_item,
    update_warehouse,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/inventory", tags=["Inventory"])


# --- warehouses ---------------------------------------------------------


@router.get("/warehouses", response_model=list[WarehouseOut])
async def list_warehouses_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> list[WarehouseOut]:
    rows = await list_warehouses(db)
    return [WarehouseOut.model_validate(r) for r in rows]


@router.post(
    "/warehouses",
    response_model=WarehouseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_warehouse_endpoint(
    payload: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.write")),
) -> WarehouseOut:
    w = await create_warehouse(db, org_id=user.org_id, payload=payload)
    return WarehouseOut.model_validate(w)


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseOut)
async def get_warehouse_endpoint(
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> WarehouseOut:
    w = await get_warehouse(db, warehouse_id)
    return WarehouseOut.model_validate(w)


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
async def update_warehouse_endpoint(
    warehouse_id: uuid.UUID,
    payload: WarehouseUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.write")),
) -> WarehouseOut:
    w = await update_warehouse(db, warehouse_id=warehouse_id, payload=payload)
    return WarehouseOut.model_validate(w)


@router.delete(
    "/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_warehouse_endpoint(
    warehouse_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.write")),
) -> Response:
    await delete_warehouse(db, warehouse_id=warehouse_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- items --------------------------------------------------------------


@router.get("/items", response_model=InventoryItemListResponse)
async def list_items_endpoint(
    warehouse_id: Optional[uuid.UUID] = Query(default=None),
    category: Optional[str] = Query(default=None, max_length=64),
    q: Optional[str] = Query(default=None, max_length=255),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> InventoryItemListResponse:
    rows, total = await list_items(
        db,
        warehouse_id=warehouse_id,
        category=category,
        q=q,
        active_only=active_only,
        page=page,
        size=size,
    )
    return InventoryItemListResponse(
        items=[InventoryItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "/items",
    response_model=InventoryItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_item_endpoint(
    payload: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.write")),
) -> InventoryItemOut:
    item = await create_item(db, org_id=user.org_id, payload=payload)
    return InventoryItemOut.model_validate(item)


@router.post(
    "/items/full",
    response_model=InventoryItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_item_full_endpoint(
    payload: InventoryItemFullCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.write")),
) -> InventoryItemOut:
    """Atomic create: a catalog row + an inventory row in one
    transaction. Used by the Add Product modal — either both rows
    land, or neither does (no half-created products).

    `description` is stored on `catalog_items.custom_data.description`.
    """
    # 1. Validate the warehouse exists in this org (404 friendlier than
    # a generic FK violation).
    wh = await get_warehouse(db, payload.warehouse_id)

    # 2. Create the catalog row first.
    catalog = CatalogItem(
        org_id=user.org_id,
        sku=payload.sku.strip().upper(),
        name=payload.name,
        category=payload.category,
        price=payload.price,
        custom_data=(
            {"description": payload.description} if payload.description else {}
        ),
        is_active=payload.is_active,
    )
    db.add(catalog)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"catalog SKU '{payload.sku}' already exists for this org",
        )

    # 3. Create the inventory row referencing the freshly-created
    # catalog row. Same transaction → both succeed or both rollback.
    inv = InventoryItem(
        org_id=user.org_id,
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
    db.add(inv)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"inventory item with SKU '{payload.sku}' already exists "
                f"in this warehouse"
            ),
        )
    await db.refresh(inv)
    return InventoryItemOut.model_validate(inv)


@router.post(
    "/items/{item_id}/cover", response_model=CoverUploadResponse
)
async def upload_cover_endpoint(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.write")),
) -> CoverUploadResponse:
    """Multipart upload of a single cover image. Saved under
    `./storage/{org}/inventory/{item}/cover.<ext>` via the storage
    backend; the served URL is persisted on `inventory_items.cover_url`.
    """
    item = await get_item(db, item_id)

    # Sniff extension from filename / content-type. Default to .jpg.
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    storage_path = f"{user.org_id}/inventory/{item.id}/cover.{ext}"
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )
    ref = get_storage().put(
        storage_path, data, content_type=file.content_type or "application/octet-stream"
    )

    item.cover_url = ref.url
    await db.commit()
    await db.refresh(item)
    return CoverUploadResponse(cover_url=ref.url)


@router.get("/items/{item_id}", response_model=InventoryItemOut)
async def get_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> InventoryItemOut:
    item = await get_item(db, item_id)
    return InventoryItemOut.model_validate(item)


@router.patch("/items/{item_id}", response_model=InventoryItemOut)
async def update_item_endpoint(
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.write")),
) -> InventoryItemOut:
    item = await update_item(db, item_id=item_id, payload=payload)
    return InventoryItemOut.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.write")),
) -> Response:
    await delete_item(db, item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- movements ----------------------------------------------------------


@router.get(
    "/items/{item_id}/movements", response_model=list[MovementOut]
)
async def list_movements_endpoint(
    item_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> list[MovementOut]:
    await get_item(db, item_id)
    rows = await list_movements(db, item_id=item_id, limit=limit)
    return [MovementOut.model_validate(r) for r in rows]


@router.post(
    "/items/{item_id}/movements",
    response_model=MovementOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_movement_endpoint(
    item_id: uuid.UUID,
    payload: MovementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MovementOut:
    # Per-type permission check — dispatch + transfer have dedicated
    # permissions because they typically reflect customer-visible
    # state changes.
    required = "inventory.write"
    if payload.type == MovementType.dispatch:
        required = "inventory.dispatch"
    elif payload.type == MovementType.transfer:
        required = "inventory.transfer"

    from src.app.core.permissions.service import list_permissions_for_role

    granted = {
        p.key for p in await list_permissions_for_role(db, user.role_id)
    }
    if required not in granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {required}",
        )

    movement = await record_movement(
        db,
        item_id=item_id,
        user_id=user.legacy_uuid,
        type_=payload.type,
        qty=payload.qty,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        notes=payload.notes,
    )
    return MovementOut.model_validate(movement)


# --- alerts -------------------------------------------------------------


@router.get("/alerts", response_model=list[StockAlertOut])
async def list_alerts_endpoint(
    severity: Optional[AlertSeverity] = Query(default=None),
    status_: Optional[AlertStatus] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.read")),
) -> list[StockAlertOut]:
    rows, _total = await list_alerts(
        db,
        severity=severity,
        status_filter=status_,
        page=page,
        size=size,
    )
    return [StockAlertOut.model_validate(r) for r in rows]


@router.patch("/alerts/{alert_id}", response_model=StockAlertOut)
async def update_alert_endpoint(
    alert_id: uuid.UUID,
    payload: StockAlertPatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("inventory.write")),
) -> StockAlertOut:
    alert = await update_alert_status(
        db, alert_id=alert_id, new_status=payload.status
    )
    return StockAlertOut.model_validate(alert)
