"""HTTP routes for the furniture-pack custom-orders module.

  /api/v1/custom-orders                            (CRUD + filters)
  /api/v1/custom-orders/{id}/move-stage            (POST)
  /api/v1/custom-orders/{id}/measurements          (GET list, POST add)
  /api/v1/custom-orders/{id}/photos                (GET list, POST multipart)
  /api/v1/custom-orders/{id}/stage-history         (GET list)

Permissions:
  - `custom_orders.read`  → all GETs
  - `custom_orders.write` → create / update / delete / measurements / photos
  - `custom_orders.move`  → move-stage
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.packs.furniture.modules.custom_orders.schemas import (
    CustomOrderCreate,
    CustomOrderListResponse,
    CustomOrderOut,
    CustomOrderUpdate,
    MeasurementCreate,
    MeasurementOut,
    MoveStagePayload,
    PhotoOut,
    StageHistoryOut,
)
from src.app.packs.furniture.modules.custom_orders.service import (
    add_measurement,
    add_photo,
    create_order,
    delete_order,
    get_order,
    list_measurements,
    list_orders,
    list_photos,
    list_stage_history,
    move_stage,
    update_order,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/custom-orders", tags=["Custom Orders"])


# --- orders -------------------------------------------------------------


@router.get("", response_model=CustomOrderListResponse)
async def list_orders_endpoint(
    stage: Optional[str] = Query(default=None, max_length=64),
    assigned_to_id: Optional[uuid.UUID] = Query(default=None),
    contact_id: Optional[uuid.UUID] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.read")),
) -> CustomOrderListResponse:
    rows, total = await list_orders(
        db,
        stage=stage,
        assigned_to_id=assigned_to_id,
        contact_id=contact_id,
        page=page,
        size=size,
    )
    return CustomOrderListResponse(
        items=[CustomOrderOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=CustomOrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_endpoint(
    payload: CustomOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_orders.write")),
) -> CustomOrderOut:
    order = await create_order(
        db, org_id=user.org_id, user_id=user.id, payload=payload
    )
    return CustomOrderOut.model_validate(order)


@router.get("/{order_id}", response_model=CustomOrderOut)
async def get_order_endpoint(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.read")),
) -> CustomOrderOut:
    order = await get_order(db, order_id)
    return CustomOrderOut.model_validate(order)


@router.patch("/{order_id}", response_model=CustomOrderOut)
async def update_order_endpoint(
    order_id: uuid.UUID,
    payload: CustomOrderUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.write")),
) -> CustomOrderOut:
    order = await update_order(db, order_id=order_id, payload=payload)
    return CustomOrderOut.model_validate(order)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order_endpoint(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.write")),
) -> Response:
    await delete_order(db, order_id=order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- stage transition ---------------------------------------------------


@router.post("/{order_id}/move-stage", response_model=CustomOrderOut)
async def move_stage_endpoint(
    order_id: uuid.UUID,
    payload: MoveStagePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_orders.move")),
) -> CustomOrderOut:
    order = await move_stage(
        db,
        order_id=order_id,
        user_id=user.id,
        to_stage=payload.to_stage,
        notes=payload.notes,
    )
    return CustomOrderOut.model_validate(order)


# --- measurements -------------------------------------------------------


@router.get(
    "/{order_id}/measurements", response_model=list[MeasurementOut]
)
async def list_measurements_endpoint(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.read")),
) -> list[MeasurementOut]:
    await get_order(db, order_id)
    rows = await list_measurements(db, order_id=order_id)
    return [MeasurementOut.model_validate(r) for r in rows]


@router.post(
    "/{order_id}/measurements",
    response_model=MeasurementOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_measurement_endpoint(
    order_id: uuid.UUID,
    payload: MeasurementCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.write")),
) -> MeasurementOut:
    m = await add_measurement(db, order_id=order_id, payload=payload)
    return MeasurementOut.model_validate(m)


# --- photos -------------------------------------------------------------


@router.get("/{order_id}/photos", response_model=list[PhotoOut])
async def list_photos_endpoint(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.read")),
) -> list[PhotoOut]:
    await get_order(db, order_id)
    rows = await list_photos(db, order_id=order_id)
    return [PhotoOut.model_validate(r) for r in rows]


@router.post(
    "/{order_id}/photos",
    response_model=PhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_photo_endpoint(
    order_id: uuid.UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.write")),
) -> PhotoOut:
    """Multipart upload of a single site / progress photo. Stored under
    `./storage/{org}/custom_orders/{order}/photo-{uuid}.<ext>` via the
    storage backend; the served URL lands on `fp_custom_order_photos.url`.
    """
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )

    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]

    photo = await add_photo(
        db,
        order_id=order_id,
        data=data,
        content_type=file.content_type or "application/octet-stream",
        file_extension=ext,
        caption=caption,
    )
    return PhotoOut.model_validate(photo)


# --- stage history reads -----------------------------------------------


@router.get(
    "/{order_id}/stage-history", response_model=list[StageHistoryOut]
)
async def list_stage_history_endpoint(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_orders.read")),
) -> list[StageHistoryOut]:
    await get_order(db, order_id)
    rows = await list_stage_history(db, order_id=order_id)
    return [StageHistoryOut.model_validate(r) for r in rows]
