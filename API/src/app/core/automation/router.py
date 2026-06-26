"""HTTP routes for the automation engine.

Nine endpoints mounted under ``/api/v1/automations``:

  GET    /api/v1/automations/triggers                 — paginated list
  POST   /api/v1/automations/triggers                 — create
  GET    /api/v1/automations/triggers/{id}            — read
  PATCH  /api/v1/automations/triggers/{id}            — edit
  POST   /api/v1/automations/triggers/{id}/enable     — toggle on
  POST   /api/v1/automations/triggers/{id}/disable    — toggle off
  DELETE /api/v1/automations/triggers/{id}            — hard delete
  GET    /api/v1/automations/triggers/{id}/runs       — run history
  GET    /api/v1/automations/event-types              — discovery

Reads are gated on :data:`PERM_READ`; mutations on :data:`PERM_WRITE`.
Run-history is gated tighter on :data:`PERM_RUNS_READ` (payloads can
carry sensitive contact data). All error mapping flows through
``_automation_http_map`` so the operator sees consistent ``detail``
shapes: 404 / 409 / 422 cover :class:`TriggerNotFound`,
:class:`DuplicateTriggerName`, :class:`InvalidCondition` +
:class:`MissingTemplateForChannel`.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.automation import data_access, event_catalog
from src.app.core.automation import service as automation_service
from src.app.core.automation.exceptions import (
    AutomationError,
    DuplicateTriggerName,
    InvalidCondition,
    MissingTemplateForChannel,
    TriggerNotFound,
)
from src.app.core.automation.models import AutomationRunStatus
from src.app.core.automation.permissions import (
    PERM_READ,
    PERM_RUNS_READ,
    PERM_WRITE,
)
from src.app.core.automation.schemas import (
    RunRead,
    TriggerCreate,
    TriggerRead,
    TriggerUpdate,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/automations", tags=["Automations"])


# --- response wrappers ----------------------------------------------


class TriggerListResponse(BaseModel):
    items: list[TriggerRead]
    total: int
    limit: int
    offset: int


class RunListResponse(BaseModel):
    items: list[RunRead]
    total: int
    limit: int
    offset: int


class EventCatalogEntry(BaseModel):
    """Wire shape for the discovery endpoint — one row per event."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    label: str
    description: str
    sample_payload: dict


# --- exception mapping ----------------------------------------------


def _automation_http_map(exc: AutomationError) -> HTTPException:
    if isinstance(exc, TriggerNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, DuplicateTriggerName):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, (InvalidCondition, MissingTemplateForChannel)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": str(exc)},
    )


# --- trigger CRUD ---------------------------------------------------


@router.get("/triggers", response_model=TriggerListResponse)
async def list_triggers_endpoint(
    event_type: Optional[str] = Query(default=None, max_length=200),
    enabled: Optional[bool] = Query(default=None),
    channel: Optional[ConversationChannel] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TriggerListResponse:
    rows, total = await automation_service.list_triggers(
        db,
        org_id=user.org_id,
        event_type=event_type,
        enabled=enabled,
        channel=channel,
        q=q,
        limit=limit,
        offset=offset,
    )
    return TriggerListResponse(
        items=[TriggerRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/triggers",
    response_model=TriggerRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_trigger_endpoint(
    payload: TriggerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.create_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.get("/triggers/{trigger_id}", response_model=TriggerRead)
async def get_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TriggerRead:
    try:
        trigger = await automation_service.get_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.patch("/triggers/{trigger_id}", response_model=TriggerRead)
async def update_trigger_endpoint(
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.update_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
            payload=payload,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.post(
    "/triggers/{trigger_id}/enable", response_model=TriggerRead
)
async def enable_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.enable_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.post(
    "/triggers/{trigger_id}/disable", response_model=TriggerRead
)
async def disable_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.disable_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.delete(
    "/triggers/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    try:
        await automation_service.delete_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- run history ----------------------------------------------------


@router.get(
    "/triggers/{trigger_id}/runs", response_model=RunListResponse
)
async def list_runs_endpoint(
    trigger_id: uuid.UUID,
    run_status: Optional[AutomationRunStatus] = Query(
        default=None, alias="status"
    ),
    since: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_RUNS_READ)),
) -> RunListResponse:
    """Per-trigger run history. ``status`` query param uses
    :class:`AutomationRunStatus`; ``since`` is an ISO-8601 timestamp
    (e.g. ``2026-06-26T00:00:00Z``). The endpoint refuses unknown
    trigger ids with 404 — RLS-scoped lookup."""
    try:
        # Confirm the trigger exists in this org (RLS + 404 mapping).
        await automation_service.get_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    rows, total = await data_access.list_runs(
        db,
        org_id=user.org_id,
        trigger_id=trigger_id,
        status=run_status,
        since=since,
        limit=limit,
        offset=offset,
    )
    return RunListResponse(
        items=[RunRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- event discovery ------------------------------------------------


@router.get("/event-types", response_model=list[EventCatalogEntry])
async def list_event_types_endpoint(
    _user: User = Depends(require_permissions(PERM_READ)),
) -> list[EventCatalogEntry]:
    """Discovery catalog — feeds the trigger editor's event picker
    + the variable-hint side panel. Static per-deploy (no DB hit)."""
    return [
        EventCatalogEntry(
            event_type=entry.event_type,
            label=entry.label,
            description=entry.description,
            sample_payload=entry.sample_payload,
        )
        for entry in event_catalog.list_catalog()
    ]


__all__ = ["router"]
