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
from typing import Literal

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
    WalkInBulkDelete,
    WalkInBulkDeleteResult,
    WalkInBulkReassign,
    WalkInBulkReassignResult,
    WalkInConvertRequest,
    WalkInConvertResponse,
    WalkInCreate,
    WalkInOut,
    WalkInReassign,
    WalkInsRollup,
    WalkInUpdate,
)
from src.app.core.walk_ins.service import (
    bulk_checkout_walk_ins,
    bulk_delete_walk_ins,
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
    walk_ins_rollup,
)
from src.app.core.permissions.service import role_has_permission
from src.app.shared.db import get_db

router = APIRouter(prefix="/walk-ins", tags=["Walk-ins"])


@router.get("", response_model=list[WalkInOut])
async def list_walk_ins_endpoint(
    status_filter: WalkInStatus | None = Query(default=None, alias="status"),
    assigned_to: list[uuid.UUID] | None = Query(
        default=None,
        description=(
            "Filter by owner UUID. Repeat the param "
            "(`?assigned_to=<uuid>&assigned_to=<uuid>`) to match any of "
            "several owners — the column-header Owner popover sends this shape."
        ),
    ),
    open_only: bool = Query(default=False),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    sort: Literal["time_in", "created_at", "last_activity_at"] = Query(default="time_in"),
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
    walk_in, contact, was_created = await quick_register(db, org_id=user.org_id, payload=payload)
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


# --- Static /rollup route: MUST come BEFORE /{walk_in_id} so the UUID
# capture doesn't eat "rollup" and 422. Same trap the leads router hits
# with /pipeline-value + /routing-config. ------------------------------


@router.get("/rollup", response_model=WalkInsRollup)
async def walk_ins_rollup_endpoint(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("walkins.read")),
) -> WalkInsRollup:
    """W7 — Server-side KPI roll-up for the walk-ins page header.

    Scope follows the same row-visibility rule as the list endpoint:
    callers with ``users.read`` see the whole org, everyone else sees
    only their own contribution."""
    is_org_scope = await role_has_permission(db, caller.role_id, "users.read")
    rollup = await walk_ins_rollup(
        db,
        org_id=caller.org_id,
        assigned_to=None if is_org_scope else caller.legacy_uuid,
    )
    return WalkInsRollup.model_validate(rollup)


@router.get("/{walk_in_id}", response_model=WalkInOut)
async def get_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("walkins.read")),
) -> WalkInOut:
    walk_in = await get_walk_in(db, walk_in_id)
    if walk_in is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found")
    # Local import mirrors walk_ins/service.py — avoids a permissions<->walk_ins
    # circular import at module load.
    from src.app.core.permissions.service import role_has_permission

    # Row-level visibility: non-privileged callers can only fetch
    # walk-ins assigned to them. 404 (not 403) so we don't leak the
    # existence of walk-ins outside the caller's book.
    if walk_in.assigned_to_id != caller.legacy_uuid and not await role_has_permission(
        db, caller.role_id, "users.read"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="walk-in not found")
    return WalkInOut.model_validate(walk_in)


@router.patch("/{walk_in_id}", response_model=WalkInOut)
async def update_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    payload: WalkInUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> WalkInOut:
    # Reassigning through the edit modal must not sidestep the dedicated
    # `walkins.reassign` gate. When the PATCH includes assigned_to_id
    # (including null → explicit unassign), additionally require
    # `walkins.reassign`. `exclude_unset=True` distinguishes "not sent"
    # from "sent as null".
    changes = payload.model_dump(exclude_unset=True)
    if "assigned_to_id" in changes:
        if not await role_has_permission(db, user.role_id, "walkins.reassign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission(s): walkins.reassign",
            )
    walk_in = await update_walk_in(
        db,
        walk_in_id=walk_in_id,
        payload=payload,
        org_id=user.org_id,
    )
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
    reassigned, already_assigned = await bulk_reassign_walk_ins(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return WalkInBulkReassignResult(
        reassigned=reassigned, already_assigned=already_assigned
    )


@router.post("/bulk-checkout", response_model=WalkInBulkCheckoutResult)
async def bulk_checkout_walk_ins_endpoint(
    payload: WalkInBulkCheckout,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> WalkInBulkCheckoutResult:
    checked_out, already = await bulk_checkout_walk_ins(db, ids=payload.ids, org_id=user.org_id)
    return WalkInBulkCheckoutResult(checked_out=checked_out, already_checked_out=already)


@router.post("/bulk-delete", response_model=WalkInBulkDeleteResult)
async def bulk_delete_walk_ins_endpoint(
    payload: WalkInBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("walkins.write")),
) -> WalkInBulkDeleteResult:
    """W1 — Single-call bulk-delete replacing the frontend per-row
    loop. Mirror of ``POST /leads/bulk-delete`` — one SQL statement,
    one audit entry."""
    n = await bulk_delete_walk_ins(db, ids=payload.ids, org_id=user.org_id)
    return WalkInBulkDeleteResult(deleted=n)


@router.post("/{walk_in_id}/convert", response_model=WalkInConvertResponse)
async def convert_walk_in_endpoint(
    walk_in_id: uuid.UUID,
    payload: WalkInConvertRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write", "walkins.write")),
) -> WalkInConvertResponse:
    """Convert a walk-in to a lead. Requires BOTH `leads.write` (a
    lead is created) AND `walkins.write` (the walk-in row is mutated:
    `linked_lead_id` set). Custom roles that hold `leads.write` alone
    must not be able to mutate walk-in rows through this side door."""
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
