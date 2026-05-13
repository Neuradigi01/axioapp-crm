"""HTTP routes for the OrgSettings module.

  GET    /api/v1/settings
  PATCH  /api/v1/settings

Reads need `settings.read`; mutations need `settings.write`. There's
no `POST` or `DELETE` — the row is auto-created on first GET and
removed only via org teardown (cascade from `organizations.id`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.settings.schemas import OrgSettingsOut, OrgSettingsPatch
from src.app.core.settings.service import get_or_create, patch_settings
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=OrgSettingsOut)
async def get_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.read")),
) -> OrgSettingsOut:
    row = await get_or_create(db, org_id=user.org_id)
    return OrgSettingsOut.model_validate(row)


@router.patch("", response_model=OrgSettingsOut)
async def patch_endpoint(
    payload: OrgSettingsPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.write")),
) -> OrgSettingsOut:
    row = await patch_settings(db, org_id=user.org_id, payload=payload)
    return OrgSettingsOut.model_validate(row)
