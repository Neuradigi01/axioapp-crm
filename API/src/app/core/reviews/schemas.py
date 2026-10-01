"""Pydantic v2 schemas for the reviews module."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.app.core.reviews.models import ReviewStatus
from src.app.shared.schemas import ORMModel, PaginatedResponse


class ReviewCreate(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    source_id: str | None = Field(default=None, max_length=255)
    contact_id: uuid.UUID | None = None
    rating: int = Field(ge=1, le=5)
    text: str | None = None
    tags: list[str] = Field(default_factory=list)


class ReviewUpdate(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=32)
    source_id: str | None = Field(default=None, max_length=255)
    contact_id: uuid.UUID | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    text: str | None = None
    tags: list[str] | None = None


class ReviewReplyPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ReviewEscalatePayload(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class ReviewOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    source: str
    source_id: str | None
    contact_id: uuid.UUID | None
    rating: int
    text: str | None
    reply_text: str | None
    replied_at: datetime | None
    replied_by_id: uuid.UUID | None
    status: ReviewStatus
    tags: list[str]
    created_at: datetime


ReviewListResponse = PaginatedResponse[ReviewOut]


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
