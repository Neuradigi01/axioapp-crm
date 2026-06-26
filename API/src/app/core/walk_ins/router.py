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
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.contacts.schemas import ContactOut
from src.app.core.users.models import User
from src.app.core.walk_ins.models import WalkInStatus
from src.app.core.walk_ins.schemas import (
    QuickRegisterPayload,
    QuickRegisterResponse,
    WalkInBulkCheckout,
    WalkInBulkCheckoutResult,
    WalkInBulkReassign,
    WalkInBulkReassignResult,
    WalkInConvertRequest,
    WalkInConvertResponse,
    WalkInCreate,
    WalkInOut,
    WalkInReassign,
    WalkInUpdate,
)
from src.app.core.walk_ins.service import (
    bulk_checkout_walk_ins,
    bulk_reassign_walk_ins,
    checkout,
    convert_walk_in_to_lead,
    create_walk_in,
    delete_walk_in,
    get_walk_in,
    list_walk_ins_visible_to,
    quick_register,
    reassign_walk_in,
    update_walk_in,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/walk-ins", tags=["Walk-ins"])


@router.get("", response_model=list[WalkInOut])
async def list_walk_ins_endpoint(
    status_filter: Optional[WalkInStatus] = Query(default=None, alias="status"),
    assigned_to: Optional[uuid.UUID] = Query(default=None),
    open_only: bool = Query(default=False),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    sort: Literal["time_in", "created_at", "last_activity_at"] = Query(
        default="time_in"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("walkins.read")),
) -> list[WalkInOut]:
    rows, _ = await list_walk_ins_visible_to(
        db,
        caller=caller,
        status_filter=status_filter,
        assigned_to=assigned_to,
        open_only=open_only,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        order=order,
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
    caller: User = Depends(require_permissions("walkins.read")),
) -> WalkInOut:
    walk_in = await get_walk_in(db, walk_in_id)
    if walk_in is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found"
        )
    # Row-level visibility: non-privileged callers can only fetch
    # walk-ins assigned to them. 404 (not 403) so we don't leak the
    # existence of walk-ins outside the caller's book.
    if (
        walk_in.assigned_to_id != caller.legacy_uuid
        and not await role_has_permission(db, caller.role_id, "users.read")
    ):
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


# --- Reassign + bulk + convert endpoints ------------------------------------


@router.post("/{walk_in_id}/reassign", response_model=WalkInOut)
async def reassign_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    payload: WalkInReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.reassign")),
) -> WalkInOut:
    walk_in = await reassign_walk_in(
        db,
        walk_in_id=walk_in_id,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return WalkInOut.model_validate(walk_in)


@router.post("/bulk-reassign", response_model=WalkInBulkReassignResult)
async def bulk_reassign_walk_ins_endpoint(
    payload: WalkInBulkReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.reassign")),
) -> WalkInBulkReassignResult:
    n = await bulk_reassign_walk_ins(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return WalkInBulkReassignResult(reassigned=n)


@router.post("/bulk-checkout", response_model=WalkInBulkCheckoutResult)
async def bulk_checkout_walk_ins_endpoint(
    payload: WalkInBulkCheckout,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> WalkInBulkCheckoutResult:
    checked_out, already = await bulk_checkout_walk_ins(
        db, ids=payload.ids, org_id=user.org_id
    )
    return WalkInBulkCheckoutResult(
        checked_out=checked_out, already_checked_out=already
    )


@router.post("/{walk_in_id}/convert", response_model=WalkInConvertResponse)
async def convert_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    payload: WalkInConvertRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> WalkInConvertResponse:
    """Convert a walk-in to a lead. Requires `leads.write` (the
    feature's primary side-effect is creating a lead) plus the
    `walkins.write` the caller already needs to mutate the walk-in
    row — that's covered by the leads.write requirement here since
    any role with leads.write also has walkins.write by template."""
    walk_in, contact_id, lead_id = await convert_walk_in_to_lead(
        db,
        walk_in_id=walk_in_id,
        org_id=user.org_id,
        contact_link_mode=payload.contact_link_mode,
        linked_contact_id=payload.linked_contact_id,
        notes=payload.notes,
        actor_user_id=user.legacy_uuid,
    )
    return WalkInConvertResponse(
        walk_in_id=walk_in.id,
        contact_id=contact_id,
        lead_id=lead_id,
    )
