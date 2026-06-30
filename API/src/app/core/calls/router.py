"""HTTP routes for the call-center module.

  GET    /api/v1/calls
  POST   /api/v1/calls
  GET    /api/v1/calls/{id}
  PATCH  /api/v1/calls/{id}
  DELETE /api/v1/calls/{id}

  GET    /api/v1/calls/{id}/transcript
  PUT    /api/v1/calls/{id}/transcript

  GET    /api/v1/call-outcomes
  POST   /api/v1/call-outcomes
  PATCH  /api/v1/call-outcomes/{id}
  DELETE /api/v1/call-outcomes/{id}

  GET    /api/v1/calls/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD

Reads need `calls.read`; mutations need `calls.write`. Outcomes config
needs `calls.outcomes.manage` (admin-only). Tenant scoping is automatic
via the ORM filter on `TenantScoped`.
"""

from __future__ import annotations

import uuid
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.calls.models import CallDirection
from src.app.core.calls.schemas import (
    CallAnalyticsOut,
    CallCreate,
    CallListResponse,
    CallOut,
    CallOutcomeCreate,
    CallOutcomeOut,
    CallOutcomeUpdate,
    CallTranscriptOut,
    CallTranscriptUpsert,
    CallUpdate,
)
from src.app.core.calls.service import (
    analytics,
    create_call,
    create_outcome,
    delete_call,
    delete_outcome,
    get_call,
    get_transcript,
    list_calls,
    list_outcomes,
    update_call,
    update_outcome,
    upsert_transcript,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

calls_router = APIRouter(prefix="/calls", tags=["Calls"])
outcomes_router = APIRouter(prefix="/call-outcomes", tags=["CallOutcomes"])


# --- Analytics (must precede `/{call_id}` to avoid path conflict) ---------


@calls_router.get("/analytics", response_model=CallAnalyticsOut)
async def analytics_endpoint(
    from_: Date = Query(..., alias="from"),
    to: Date = Query(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.read")),
) -> CallAnalyticsOut:
    data = await analytics(db, from_dt=from_, to_dt=to)
    return CallAnalyticsOut(**data)


# --- Calls CRUD ------------------------------------------------------------


@calls_router.get("", response_model=CallListResponse)
async def list_calls_endpoint(
    contact_id: uuid.UUID | None = Query(default=None),
    direction: CallDirection | None = Query(default=None),
    assigned_to: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.read")),
) -> CallListResponse:
    rows, total = await list_calls(
        db,
        contact_id=contact_id,
        direction=direction,
        assigned_to_id=assigned_to,
        page=page,
        size=size,
    )
    return CallListResponse(
        items=[CallOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@calls_router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_call_endpoint(
    payload: CallCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("calls.write")),
) -> CallOut:
    call = await create_call(db, org_id=user.org_id, user_id=user.legacy_uuid, payload=payload)
    return CallOut.model_validate(call)


@calls_router.get("/{call_id}", response_model=CallOut)
async def get_call_endpoint(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.read")),
) -> CallOut:
    call = await get_call(db, call_id)
    return CallOut.model_validate(call)


@calls_router.patch("/{call_id}", response_model=CallOut)
async def update_call_endpoint(
    call_id: uuid.UUID,
    payload: CallUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.write")),
) -> CallOut:
    call = await update_call(db, call_id=call_id, payload=payload)
    return CallOut.model_validate(call)


@calls_router.delete("/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_call_endpoint(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.write")),
) -> Response:
    await delete_call(db, call_id=call_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Transcript -----------------------------------------------------------


@calls_router.get("/{call_id}/transcript", response_model=CallTranscriptOut)
async def get_transcript_endpoint(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.read")),
) -> CallTranscriptOut:
    await get_call(db, call_id)
    transcript = await get_transcript(db, call_id=call_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no transcript recorded for this call",
        )
    return CallTranscriptOut.model_validate(transcript)


@calls_router.put("/{call_id}/transcript", response_model=CallTranscriptOut)
async def upsert_transcript_endpoint(
    call_id: uuid.UUID,
    payload: CallTranscriptUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("calls.write")),
) -> CallTranscriptOut:
    transcript = await upsert_transcript(db, org_id=user.org_id, call_id=call_id, payload=payload)
    return CallTranscriptOut.model_validate(transcript)


# --- Outcomes (config) ----------------------------------------------------


@outcomes_router.get("", response_model=list[CallOutcomeOut])
async def list_outcomes_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.read")),
) -> list[CallOutcomeOut]:
    rows = await list_outcomes(db)
    return [CallOutcomeOut.model_validate(r) for r in rows]


@outcomes_router.post("", response_model=CallOutcomeOut, status_code=status.HTTP_201_CREATED)
async def create_outcome_endpoint(
    payload: CallOutcomeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("calls.outcomes.manage")),
) -> CallOutcomeOut:
    outcome = await create_outcome(db, org_id=user.org_id, payload=payload)
    return CallOutcomeOut.model_validate(outcome)


@outcomes_router.patch("/{outcome_id}", response_model=CallOutcomeOut)
async def update_outcome_endpoint(
    outcome_id: uuid.UUID,
    payload: CallOutcomeUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.outcomes.manage")),
) -> CallOutcomeOut:
    outcome = await update_outcome(db, outcome_id=outcome_id, payload=payload)
    return CallOutcomeOut.model_validate(outcome)


@outcomes_router.delete("/{outcome_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outcome_endpoint(
    outcome_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("calls.outcomes.manage")),
) -> Response:
    await delete_outcome(db, outcome_id=outcome_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
