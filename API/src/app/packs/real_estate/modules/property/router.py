"""HTTP routes for the real-estate-pack Property module.

  /api/v1/property                    (POST create, GET list)
  /api/v1/property/{id}               (GET detail, PATCH update, DELETE)
  /api/v1/property/{id}/publish       (POST)
  /api/v1/property/{id}/unpublish     (POST)
  /api/v1/property/{id}/archive       (POST)
  /api/v1/property/{id}/unarchive     (POST)
  /api/v1/property/{id}/mark-sold     (POST)

Permissions:
  - ``property.read``     → all GETs
  - ``property.write``    → POST create, PATCH update, POST mark-sold
  - ``property.publish``  → POST publish, POST unpublish
  - ``property.archive``  → POST archive, POST unarchive
  - ``property.delete``   → DELETE

Router only receives the request, resolves auth deps, and calls into
``service.py``. No SQL, no DB helpers here (enforced by the layered
architecture pin-test).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.packs.real_estate.modules.property.constants import (
    PropertyCategory,
    PropertyStatus,
    PropertyType,
)
from src.app.packs.real_estate.modules.property.schemas import (
    PropertyCreate,
    PropertyImageOut,
    PropertyImageReorderRequest,
    PropertyListFilters,
    PropertyListOut,
    PropertyOut,
    PropertyUpdate,
)
from src.app.packs.real_estate.modules.property.service import (
    archive_property,
    create_property,
    delete_property,
    delete_property_image,
    get_property,
    list_properties,
    mark_sold,
    publish_property,
    reorder_property_images,
    set_featured_image,
    unarchive_property,
    unpublish_property,
    update_property,
    upload_property_images,
)
from src.app.shared.db import get_db

router = APIRouter(prefix="/property", tags=["Property"])


# --- CRUD ---------------------------------------------------------------


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED)
async def create_property_endpoint(
    payload: PropertyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> PropertyOut:
    return await create_property(
        db,
        org_id=user.org_id,
        actor_user_id=user.legacy_uuid,
        payload=payload,
    )


@router.get("", response_model=PropertyListOut)
async def list_properties_endpoint(
    statuses: list[PropertyStatus] | None = Query(default=None),
    property_type: PropertyType | None = Query(default=None),
    category: PropertyCategory | None = Query(default=None),
    city: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=200),
    owner_id: uuid.UUID | None = Query(default=None),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    sort_by: str = Query(default="created_at"),
    sort_desc: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.read")),
) -> PropertyListOut:
    filters = PropertyListFilters(
        statuses=statuses,
        property_type=property_type,
        category=category,
        city=city,
        search=search,
        owner_id=owner_id,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        sort_desc=sort_desc,
        page=page,
        page_size=page_size,
    )
    return await list_properties(db, org_id=user.org_id, filters=filters)


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.read")),
) -> PropertyOut:
    return await get_property(db, org_id=user.org_id, property_id=property_id)


@router.patch("/{property_id}", response_model=PropertyOut)
async def update_property_endpoint(
    property_id: uuid.UUID,
    payload: PropertyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> PropertyOut:
    return await update_property(
        db,
        org_id=user.org_id,
        property_id=property_id,
        payload=payload,
    )


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.delete")),
) -> Response:
    await delete_property(db, org_id=user.org_id, property_id=property_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Lifecycle transitions ----------------------------------------------


@router.post("/{property_id}/publish", response_model=PropertyOut)
async def publish_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.publish")),
) -> PropertyOut:
    return await publish_property(db, org_id=user.org_id, property_id=property_id)


@router.post("/{property_id}/unpublish", response_model=PropertyOut)
async def unpublish_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.publish")),
) -> PropertyOut:
    return await unpublish_property(db, org_id=user.org_id, property_id=property_id)


@router.post("/{property_id}/archive", response_model=PropertyOut)
async def archive_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.archive")),
) -> PropertyOut:
    return await archive_property(db, org_id=user.org_id, property_id=property_id)


@router.post("/{property_id}/unarchive", response_model=PropertyOut)
async def unarchive_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.archive")),
) -> PropertyOut:
    return await unarchive_property(db, org_id=user.org_id, property_id=property_id)


@router.post("/{property_id}/mark-sold", response_model=PropertyOut)
async def mark_sold_endpoint(
    property_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> PropertyOut:
    return await mark_sold(db, org_id=user.org_id, property_id=property_id)


# --- Image gallery ------------------------------------------------------


@router.post(
    "/{property_id}/images",
    response_model=list[PropertyImageOut],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images_endpoint(
    property_id: uuid.UUID,
    files: list[UploadFile] = File(..., description="Multipart image files (JPEG/PNG/WebP, ≤5 MB each)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> list[PropertyImageOut]:
    tuples = [(f.filename or "", await f.read(), f.content_type) for f in files]
    inserted = await upload_property_images(
        db, org_id=user.org_id, property_id=property_id, files=tuples
    )
    return [PropertyImageOut.model_validate(i, from_attributes=True) for i in inserted]


@router.delete(
    "/{property_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_image_endpoint(
    property_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> Response:
    await delete_property_image(
        db, org_id=user.org_id, property_id=property_id, image_id=image_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{property_id}/images/reorder",
    response_model=list[PropertyImageOut],
)
async def reorder_images_endpoint(
    property_id: uuid.UUID,
    payload: PropertyImageReorderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> list[PropertyImageOut]:
    fresh = await reorder_property_images(
        db,
        org_id=user.org_id,
        property_id=property_id,
        image_ids=payload.image_ids,
    )
    return [PropertyImageOut.model_validate(i, from_attributes=True) for i in fresh]


@router.patch(
    "/{property_id}/images/{image_id}/featured",
    response_model=PropertyImageOut,
)
async def set_featured_endpoint(
    property_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("property.write")),
) -> PropertyImageOut:
    image = await set_featured_image(
        db, org_id=user.org_id, property_id=property_id, image_id=image_id
    )
    return PropertyImageOut.model_validate(image, from_attributes=True)
