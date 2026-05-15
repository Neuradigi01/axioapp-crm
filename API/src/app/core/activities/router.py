"""HTTP routes for the activities timeline.

Mounted at ``/api/v1/activities``.

  GET  /activities?entity_type=&entity_id=&page=&size=  → paginated, latest first
  POST /activities                                       → manual note only

Reads are gated by `activities.read`; writes by `activities.write`.
Tenant scoping is automatic via the ORM filter on `TenantScoped`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities.schemas import (
    ActivityCreate,
    ActivityListResponse,
    ActivityOut,
)
from src.app.core.activities.service import create_note, list_activities
from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/activities", tags=["Activities"])


@router.get("", response_model=ActivityListResponse)
async def list_activities_endpoint(
    entity_type: str = Query(..., min_length=1, max_length=64),
    entity_id: uuid.UUID = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("activities.read")),
) -> ActivityListResponse:
    rows, total = await list_activities(
        db, entity_type=entity_type, entity_id=entity_id, page=page, size=size
    )
    return ActivityListResponse(
        items=[ActivityOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "", response_model=ActivityOut, status_code=status.HTTP_201_CREATED
)
async def create_activity_note(
    payload: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("activities.write")),
) -> ActivityOut:
    note = await create_note(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        text=payload.payload["text"],
    )
    return ActivityOut.model_validate(note)
