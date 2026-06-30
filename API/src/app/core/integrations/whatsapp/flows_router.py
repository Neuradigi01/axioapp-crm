"""HTTP routes for the WhatsApp Flows surface
(whatsapp-platform-upgrade Step 25).

  GET    /api/v1/integrations/whatsapp/flows
  POST   /api/v1/integrations/whatsapp/flows
  GET    /api/v1/integrations/whatsapp/flows/{id}
  PATCH  /api/v1/integrations/whatsapp/flows/{id}
  DELETE /api/v1/integrations/whatsapp/flows/{id}
  POST   /api/v1/integrations/whatsapp/flows/{id}/publish
  POST   /api/v1/integrations/whatsapp/flows/{id}/test-send
  GET    /api/v1/integrations/whatsapp/flows/templates

Permission: ``whatsapp.flows.manage`` (Owner / Admin by default
via role templates).

The list endpoint is read-only and intentionally gates on the same
manage key — junior staff don't need visibility into the flow
library; that's a future split if/when we add a "flow author" role.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp.flows_service import (
    FlowsServiceError,
    available_templates,
    delete_flow,
    load_template,
    publish_flow,
    test_send_flow,
)
from src.app.core.integrations.whatsapp.models import WhatsAppFlow
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(
    prefix="/whatsapp/flows",
    tags=["Integrations · WhatsApp · Flows"],
)


class _FlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    category: str
    status: str
    meta_flow_id: str | None
    json_definition: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class _FlowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128)
    category: str = Field(
        description=(
            "One of appointment_booking / lead_capture / feedback / "
            "signup / custom. Determines the bundled template + the "
            "auto-action that runs on submission."
        )
    )
    # When omitted, the service loads the bundled template for the
    # category. Operators can also pass an edited JSON straight away.
    json_definition: dict[str, Any] | None = None


class _FlowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    json_definition: dict[str, Any] | None = None


class _TestSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    to_phone: str = Field(min_length=4, max_length=32)


class _TemplateOut(BaseModel):
    key: str
    label: str
    description: str


@router.get("/templates", response_model=list[_TemplateOut])
async def list_templates_endpoint(
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> list[_TemplateOut]:
    """Bundled templates for the SPA picker. Returns the four
    starter options (appointment_booking / lead_capture / feedback
    / custom). Read of this endpoint shares the manage key — the
    picker is only useful to operators who can create flows."""
    return [_TemplateOut(**t) for t in available_templates()]


@router.get("", response_model=list[_FlowOut])
async def list_flows_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> list[_FlowOut]:
    rows = (
        (await db.execute(select(WhatsAppFlow).order_by(WhatsAppFlow.created_at.desc())))
        .scalars()
        .all()
    )
    return [_FlowOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=_FlowOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_flow_endpoint(
    payload: _FlowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> _FlowOut:
    try:
        definition = payload.json_definition or load_template(payload.category)
    except FlowsServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    flow = WhatsAppFlow(
        org_id=user.org_id,
        name=payload.name,
        category=payload.category,
        status="draft",
        json_definition=definition,
        created_by_user_id=user.legacy_uuid,
    )
    db.add(flow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A flow named {payload.name!r} already exists.",
        ) from None
    await db.refresh(flow)
    return _FlowOut.model_validate(flow)


@router.get("/{flow_id}", response_model=_FlowOut)
async def get_flow_endpoint(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> _FlowOut:
    flow = await _resolve_flow(db, flow_id)
    return _FlowOut.model_validate(flow)


@router.patch("/{flow_id}", response_model=_FlowOut)
async def update_flow_endpoint(
    flow_id: uuid.UUID,
    payload: _FlowUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> _FlowOut:
    flow = await _resolve_flow(db, flow_id)
    if payload.name is not None:
        flow.name = payload.name
    if payload.json_definition is not None:
        flow.json_definition = payload.json_definition
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another flow already uses that name.",
        ) from None
    await db.refresh(flow)
    return _FlowOut.model_validate(flow)


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow_endpoint(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> Response:
    flow = await _resolve_flow(db, flow_id)
    await delete_flow(db, flow=flow)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{flow_id}/publish", response_model=_FlowOut)
async def publish_flow_endpoint(
    flow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> _FlowOut:
    flow = await _resolve_flow(db, flow_id)
    try:
        flow = await publish_flow(db, flow=flow)
    except FlowsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _FlowOut.model_validate(flow)


@router.post(
    "/{flow_id}/test-send",
    summary="Send the published flow to a phone number for smoke-testing.",
)
async def test_send_endpoint(
    flow_id: uuid.UUID,
    payload: _TestSendRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.flows.manage")),
) -> dict[str, Any]:
    flow = await _resolve_flow(db, flow_id)
    try:
        meta_response = await test_send_flow(db, flow=flow, to_phone=payload.to_phone)
    except FlowsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"sent": True, "meta": meta_response}


async def _resolve_flow(db: AsyncSession, flow_id: uuid.UUID) -> WhatsAppFlow:
    flow = (
        await db.execute(select(WhatsAppFlow).where(WhatsAppFlow.id == flow_id))
    ).scalar_one_or_none()
    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="flow not found",
        )
    return flow
