"""Pydantic v2 schemas for the reviews module."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.reviews.models import ReviewStatus


class ReviewCreate(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=255)
    contact_id: Optional[uuid.UUID] = None
    rating: int = Field(ge=1, le=5)
    text: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class ReviewUpdate(BaseModel):
    source: Optional[str] = Field(default=None, min_length=1, max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=255)
    contact_id: Optional[uuid.UUID] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    text: Optional[str] = None
    tags: Optional[list[str]] = None


class ReviewReplyPayload(BaseModel):
    text: str = Field(min_length=1)


class ReviewEscalatePayload(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    source: str
    source_id: Optional[str]
    contact_id: Optional[uuid.UUID]
    rating: int
    text: Optional[str]
    reply_text: Optional[str]
    replied_at: Optional[datetime]
    replied_by_id: Optional[uuid.UUID]
    status: ReviewStatus
    tags: list[str]
    created_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewOut]
    total: int
    page: int
    size: int


class RatingDistributionRow(BaseModel):
    rating: int
    count: int


class ReviewStatsOut(BaseModel):
    """Snapshot of the review queue health."""

    total: int
    average_rating: float
    response_rate_pct: float
    distribution: list[RatingDistributionRow]
    pending_count: int
    alerts_last_7_days: int
