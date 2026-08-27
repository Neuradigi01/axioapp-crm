"""HTTP routes for the notifications module.

  GET   /api/v1/notifications?unread=true&limit=
  PATCH /api/v1/notifications/{id}/read
  POST  /api/v1/notifications/read-all
  GET   /api/v1/notification-preferences
  PATCH /api/v1/notification-preferences/{type}

All endpoints are scoped to the caller (`user_id`). There's no
permission gate: every authenticated user can read and ack their own
notifications. Tenant scoping is automatic via the ORM filter.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.notifications.schemas import (
    AvailableNotificationType,
    NotificationOut,
    NotificationPreferenceOut,
    PreferenceUpdate,
    ReadAllResponse,
)
from src.app.core.notifications.service import (
    get_preferences,
    list_available_notification_types,
    list_for_user,
    mark_all_read,
    mark_read,
    update_preferences,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    unread: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    rows = await list_for_user(db, user_id=user.legacy_uuid, unread=unread, limit=limit)
    return [NotificationOut.model_validate(r) for r in rows]


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    notification = await mark_read(db, user_id=user.legacy_uuid, notification_id=notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="notification not found",
        )
    return NotificationOut.model_validate(notification)


@router.post("/notifications/read-all", response_model=ReadAllResponse)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReadAllResponse:
    n = await mark_all_read(db, user_id=user.legacy_uuid)
    return ReadAllResponse(marked=n)


@router.get("/notification-preferences", response_model=list[NotificationPreferenceOut])
async def list_my_preferences(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NotificationPreferenceOut]:
    rows = await get_preferences(db, user_id=user.legacy_uuid)
    return [NotificationPreferenceOut.model_validate(r) for r in rows]


@router.get(
    "/notification-preferences/available-types",
    response_model=list[AvailableNotificationType],
)
async def list_available_types(
    user: User = Depends(get_current_user),
) -> list[AvailableNotificationType]:
    """Every notification event surfaced in the Settings preferences UI,
    with display label, group, and per-channel defaults. The frontend
    renders one checkbox row per entry (grouped by ``group``) and
    overlays the user's saved ``NotificationPreference`` rows on top.

    Route order matters: declared BEFORE ``/{type}`` so FastAPI doesn't
    swallow ``available-types`` as a ``type`` path param.
    """
    return list_available_notification_types()


@router.patch(
    "/notification-preferences/{type}",
    response_model=list[NotificationPreferenceOut],
)
async def update_my_preferences(
    type: str,
    payload: PreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NotificationPreferenceOut]:
    rows = await update_preferences(
        db, org_id=user.org_id, user_id=user.legacy_uuid, type_=type, payload=payload
    )
    return [NotificationPreferenceOut.model_validate(r) for r in rows]
