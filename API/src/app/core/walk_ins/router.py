"""HTTP routes for the walk-ins module.

  GET    /api/v1/walk-ins?status=&assigned_to=&open_only=&page=&size=
  POST   /api/v1/walk-ins                    → standard create (existing contact_id)
  POST   /api/v1/walk-ins/quick-register     → reception-desk one-shot
  GET    /api/v1/walk-ins/{id}
  PATCH  /api/v1/walk-ins/{id}
  PATCH  /api/v1/walk-ins/{id}/checkout      → stamps time_out
  DELETE /api/v1/walk-ins/{id}

Reads need `walkins.read`; writes need `walkins.write`.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.contacts.schemas import ContactOut
from src.app.core.users.models import User
from src.app.core.walk_ins.models import WalkInStatus
from src.app.core.walk_ins.schemas import (
    QuickRegisterPayload,
    QuickRegisterResponse,
    WalkInCreate,
    WalkInOut,
    WalkInUpdate,
)
from src.app.core.walk_ins.service import (
    checkout,
    create_walk_in,
    delete_walk_in,
    get_walk_in,
    list_walk_ins,
    quick_register,
    update_walk_in,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/walk-ins", tags=["Walk-ins"])


@router.get("", response_model=list[WalkInOut])
async def list_walk_ins_endpoint(
    status_filter: Optional[WalkInStatus] = Query(default=None, alias="status"),
    assigned_to: Optional[uuid.UUID] = Query(default=None),
    open_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("walkins.read")),
) -> list[WalkInOut]:
    rows, _ = await list_walk_ins(
        db,
        status_filter=status_filter,
        assigned_to=assigned_to,
        open_only=open_only,
        page=page,
        size=size,
    )
    return [WalkInOut.model_validate(r) for r in rows]


@router.post(
    "/quick-register",
    response_model=QuickRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def quick_register_endpoint(
    payload: QuickRegisterPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> QuickRegisterResponse:
    walk_in, contact, was_created = await quick_register(
        db, org_id=user.org_id, payload=payload
    )
    return QuickRegisterResponse(
        walk_in=WalkInOut.model_validate(walk_in),
        contact=ContactOut.model_validate(contact),
        contact_was_created=was_created,
    )


@router.post("", response_model=WalkInOut, status_code=status.HTTP_201_CREATED)
async def create_walk_in_endpoint(
    payload: WalkInCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> WalkInOut:
    walk_in = await create_walk_in(db, org_id=user.org_id, payload=payload)
    return WalkInOut.model_validate(walk_in)


@router.get("/{walk_in_id}", response_model=WalkInOut)
async def get_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("walkins.read")),
) -> WalkInOut:
    walk_in = await get_walk_in(db, walk_in_id)
    if walk_in is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found"
        )
    return WalkInOut.model_validate(walk_in)


@router.patch("/{walk_in_id}", response_model=WalkInOut)
async def update_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    payload: WalkInUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("walkins.write")),
) -> WalkInOut:
    walk_in = await update_walk_in(db, walk_in_id=walk_in_id, payload=payload)
    return WalkInOut.model_validate(walk_in)


@router.patch("/{walk_in_id}/checkout", response_model=WalkInOut)
async def checkout_endpoint(
    walk_in_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("walkins.write")),
) -> WalkInOut:
    walk_in = await checkout(db, walk_in_id=walk_in_id)
    return WalkInOut.model_validate(walk_in)


@router.delete("/{walk_in_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("walkins.write")),
) -> Response:
    await delete_walk_in(db, walk_in_id=walk_in_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
