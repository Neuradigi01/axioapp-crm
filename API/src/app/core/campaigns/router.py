"""HTTP routes for the campaigns module.

  GET    /api/v1/campaigns
  POST   /api/v1/campaigns
  GET    /api/v1/campaigns/{id}
  PATCH  /api/v1/campaigns/{id}
  DELETE /api/v1/campaigns/{id}
  POST   /api/v1/campaigns/{id}/start
  GET    /api/v1/campaigns/{id}/stats

Reads need `campaigns.read`; mutations need `campaigns.write`; starting
a campaign needs the separate `campaigns.send` permission so an admin
can grant edit rights without granting send-to-customers rights.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.campaigns.models import CampaignMessageStatus
from src.app.core.campaigns.schemas import (
    CampaignCreate,
    CampaignListResponse,
    CampaignMessageOut,
    CampaignOut,
    CampaignStartResponse,
    CampaignStatsOut,
    CampaignUpdate,
)
from src.app.core.campaigns.service import (
    create_campaign,
    delete_campaign,
    enqueue,
    get_campaign,
    list_campaigns,
    list_messages,
    retry_message,
    stats,
    update_campaign,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.get("", response_model=CampaignListResponse)
async def list_endpoint(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> CampaignListResponse:
    rows, total = await list_campaigns(db, page=page, size=size)
    return CampaignListResponse(
        items=[CampaignOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "", response_model=CampaignOut, status_code=status.HTTP_201_CREATED
)
async def create_endpoint(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("campaigns.write")),
) -> CampaignOut:
    campaign = await create_campaign(
        db, org_id=user.org_id, user_id=user.legacy_uuid, payload=payload
    )
    return CampaignOut.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_endpoint(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> CampaignOut:
    campaign = await get_campaign(db, campaign_id)
    return CampaignOut.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_endpoint(
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.write")),
) -> CampaignOut:
    campaign = await update_campaign(
        db, campaign_id=campaign_id, payload=payload
    )
    return CampaignOut.model_validate(campaign)


@router.delete(
    "/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_endpoint(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.write")),
) -> Response:
    await delete_campaign(db, campaign_id=campaign_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{campaign_id}/start", response_model=CampaignStartResponse
)
async def start_endpoint(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.send")),
) -> CampaignStartResponse:
    result = await enqueue(db, campaign_id=campaign_id)
    return CampaignStartResponse(**result)


@router.get("/{campaign_id}/stats", response_model=CampaignStatsOut)
async def stats_endpoint(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> CampaignStatsOut:
    data = await stats(db, campaign_id=campaign_id)
    return CampaignStatsOut(**data)


@router.get(
    "/{campaign_id}/messages",
    response_model=list[CampaignMessageOut],
)
async def list_messages_endpoint(
    campaign_id: uuid.UUID,
    status_: Optional[CampaignMessageStatus] = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> list[CampaignMessageOut]:
    rows, _total = await list_messages(
        db,
        campaign_id=campaign_id,
        status_filter=status_,
        page=page,
        size=size,
    )
    return [CampaignMessageOut.model_validate(r) for r in rows]


@router.post(
    "/{campaign_id}/messages/{message_id}/retry",
    response_model=CampaignMessageOut,
)
async def retry_message_endpoint(
    campaign_id: uuid.UUID,
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.send")),
) -> CampaignMessageOut:
    msg = await retry_message(
        db, campaign_id=campaign_id, message_id=message_id
    )
    return CampaignMessageOut.model_validate(msg)
