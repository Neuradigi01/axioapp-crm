"""Pydantic v2 schemas for the campaigns module."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.campaigns.models import CampaignMessageStatus, CampaignStatus
from src.app.core.conversations.models import ConversationChannel


class AudienceFilter(BaseModel):
    """Same shape as `/contacts` list query — q / source / tag."""

    q: Optional[str] = None
    source: Optional[str] = None
    tag: Optional[str] = None


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel: ConversationChannel
    audience_filter: AudienceFilter = Field(default_factory=AudienceFilter)
    template: str = Field(min_length=1, max_length=4096)
    schedule_at: Optional[datetime] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    audience_filter: Optional[AudienceFilter] = None
    template: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    schedule_at: Optional[datetime] = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    channel: ConversationChannel
    audience_filter: dict[str, Any]
    template: str
    schedule_at: Optional[datetime]
    status: CampaignStatus
    created_by_id: Optional[uuid.UUID]
    created_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignOut]
    total: int
    page: int
    size: int


class CampaignMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    channel_message_id: Optional[str]
    status: CampaignMessageStatus
    error: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime


class CampaignStatsOut(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    queued: int
    sent: int
    delivered: int
    read: int
    failed: int


class CampaignStartResponse(BaseModel):
    campaign_id: uuid.UUID
    status: CampaignStatus
    audience_size: int
    chunks_enqueued: int
    scheduled_at: Optional[datetime]
