"""HTTP routes for the leads module.

  GET    /api/v1/leads                  → paginated list with filters
  POST   /api/v1/leads                  → create
  GET    /api/v1/leads/{id}             → get one
  PATCH  /api/v1/leads/{id}             → partial update (NOT stage)
  DELETE /api/v1/leads/{id}
  POST   /api/v1/leads/{id}/move-stage  → kanban drag-drop endpoint

Reads gated by `leads.read`; writes (incl. move-stage) by `leads.write`.
The dynamic ``custom.<key>=<value>`` filter is parsed off
`Request.query_params` the same way the contacts router handles it.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.leads.models import LeadStatus
from src.app.core.leads.schemas import (
    LeadCreate,
    LeadListResponse,
    LeadOut,
    LeadUpdate,
    MoveStageRequest,
)
from src.app.core.leads.service import (
    create_lead,
    delete_lead,
    get_lead,
    list_leads,
    move_stage_for_lead,
    update_lead,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/leads", tags=["Leads"])

_CUSTOM_PREFIX = "custom."


def _extract_custom_filters(request: Request) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw_key, value in request.query_params.multi_items():
        if raw_key.startswith(_CUSTOM_PREFIX) and len(raw_key) > len(_CUSTOM_PREFIX):
            out.append((raw_key[len(_CUSTOM_PREFIX) :], value))
    return out


@router.get("", response_model=LeadListResponse)
async def list_leads_endpoint(
    request: Request,
    stage: Optional[str] = Query(default=None, max_length=64),
    status_filter: Optional[LeadStatus] = Query(default=None, alias="status"),
    assigned_to: Optional[uuid.UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    source: Optional[str] = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.read")),
) -> LeadListResponse:
    rows, total = await list_leads(
        db,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        q=q,
        source=source,
        custom_filters=_extract_custom_filters(request),
        page=page,
        size=size,
    )
    return LeadListResponse(
        items=[LeadOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead_endpoint(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadOut:
    lead = await create_lead(db, org_id=user.org_id, payload=payload)
    return LeadOut.model_validate(lead)


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead_endpoint(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.read")),
) -> LeadOut:
    lead = await get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead_endpoint(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.write")),
) -> LeadOut:
    lead = await update_lead(db, lead_id=lead_id, payload=payload)
    return LeadOut.model_validate(lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_endpoint(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.write")),
) -> Response:
    await delete_lead(db, lead_id=lead_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{lead_id}/move-stage", response_model=LeadOut)
async def move_lead_stage_endpoint(
    lead_id: uuid.UUID,
    payload: MoveStageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadOut:
    lead = await move_stage_for_lead(
        db, lead_id=lead_id, to_stage=payload.to_stage, user_id=user.legacy_uuid
    )
    return LeadOut.model_validate(lead)
