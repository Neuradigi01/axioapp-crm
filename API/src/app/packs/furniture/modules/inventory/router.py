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
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.users.models import User
from src.app.packs.furniture.modules.inventory.models import (
    AlertSeverity,
    AlertStatus,
    MovementType,
)
from src.app.packs.furniture.modules.inventory.schemas import (
    CoverUploadResponse,
    InventoryItemCreate,
    InventoryItemFullCreate,
    InventoryItemHydrateRequest,
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
from src.app.packs.furniture.modules.inventory.service import (
    create_item,
    create_item_full,
    create_warehouse,
    delete_item,
    delete_warehouse,
    get_item,
    get_warehouse,
    hydrate_items_by_ids,
    list_alerts,
    list_items,
    list_movements,
    list_warehouses,
    record_movement,
    set_item_cover,
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


@router.delete("/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
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
    warehouse_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=255),
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
    transaction. Used by the Add Product modal."""
    inv = await create_item_full(db, org_id=user.org_id, payload=payload)
    return InventoryItemOut.model_validate(inv)


@router.post("/items/{item_id}/cover", response_model=CoverUploadResponse)
async def upload_cover_endpoint(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.write")),
) -> CoverUploadResponse:
    """Multipart upload of a single cover image. Saved under
    `./storage/{org}/inventory/{item}/cover.<ext>` via the storage
    backend; the served URL is persisted on `inventory_items.cover_url`."""
    data = await file.read()
    cover_url = await set_item_cover(
        db,
        item_id=item_id,
        org_id=user.org_id,
        file_bytes=data,
    )
    return CoverUploadResponse(cover_url=cover_url)


@router.post("/items/hydrate", response_model=list[InventoryItemOut])
async def hydrate_items_endpoint(
    payload: InventoryItemHydrateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("inventory.read")),
) -> list[InventoryItemOut]:
    """Batch-fetch inventory item rows by id list. Replaces the
    ``N × GET /items/{item_id}`` fan-out from list pages that render
    item context per row (e.g. stock-alerts).

    Route order matters: declared BEFORE ``/items/{item_id}`` so
    FastAPI doesn't swallow ``"hydrate"`` as a UUID and 422.
    """
    rows = await hydrate_items_by_ids(db, org_id=user.org_id, ids=payload.ids)
    return [InventoryItemOut.model_validate(r) for r in rows]


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


@router.get("/items/{item_id}/movements", response_model=list[MovementOut])
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

    granted = {p.key for p in await list_permissions_for_role(db, user.role_id)}
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
    severity: AlertSeverity | None = Query(default=None),
    status_: AlertStatus | None = Query(default=None, alias="status"),
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
    alert = await update_alert_status(db, alert_id=alert_id, new_status=payload.status)
    return StockAlertOut.model_validate(alert)
