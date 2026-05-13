"""HTTP routes for the catalog module.

  GET    /api/v1/catalog?q=&category=&active_only=&page=&size=
  POST   /api/v1/catalog
  GET    /api/v1/catalog/{id}
  PATCH  /api/v1/catalog/{id}
  DELETE /api/v1/catalog/{id}

Reads need `catalog.read`; writes need `catalog.write`. Tenant scoping
is automatic via the ORM filter on `TenantScoped`.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.catalog.schemas import (
    CatalogItemCreate,
    CatalogItemOut,
    CatalogItemUpdate,
    CatalogListResponse,
)
from src.app.core.catalog.service import (
    create_item,
    delete_item,
    get_item,
    list_items,
    update_item,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("", response_model=CatalogListResponse)
async def list_items_endpoint(
    q: Optional[str] = Query(default=None, max_length=255),
    category: Optional[str] = Query(default=None, max_length=64),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.read")),
) -> CatalogListResponse:
    rows, total = await list_items(
        db,
        q=q,
        category=category,
        active_only=active_only,
        page=page,
        size=size,
    )
    return CatalogListResponse(
        items=[CatalogItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "", response_model=CatalogItemOut, status_code=status.HTTP_201_CREATED
)
async def create_item_endpoint(
    payload: CatalogItemCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    item = await create_item(db, org_id=user.org_id, payload=payload)
    return CatalogItemOut.model_validate(item)


@router.get("/{item_id}", response_model=CatalogItemOut)
async def get_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.read")),
) -> CatalogItemOut:
    item = await get_item(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="catalog item not found",
        )
    return CatalogItemOut.model_validate(item)


@router.patch("/{item_id}", response_model=CatalogItemOut)
async def update_item_endpoint(
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    item = await update_item(db, item_id=item_id, payload=payload)
    return CatalogItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> Response:
    await delete_item(db, item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
