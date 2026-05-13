"""HTTP routes for the reviews module.

  GET    /api/v1/reviews                  (with filters: source, rating, status)
  POST   /api/v1/reviews
  GET    /api/v1/reviews/stats
  GET    /api/v1/reviews/{id}
  PATCH  /api/v1/reviews/{id}
  DELETE /api/v1/reviews/{id}
  POST   /api/v1/reviews/{id}/reply
  POST   /api/v1/reviews/{id}/escalate

Reads need `reviews.read`; mutations need `reviews.write`. Tenant
scoping is automatic via the ORM filter on `TenantScoped`.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.reviews.models import ReviewStatus
from src.app.core.reviews.schemas import (
    ReviewCreate,
    ReviewEscalatePayload,
    ReviewListResponse,
    ReviewOut,
    ReviewReplyPayload,
    ReviewStatsOut,
    ReviewUpdate,
)
from src.app.core.reviews.service import (
    create_review,
    delete_review,
    escalate_review,
    get_review,
    list_reviews,
    reply_to_review,
    stats,
    update_review,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/reviews", tags=["Reviews"])


# Stats lives before `/{id}` to avoid path collision.
@router.get("/stats", response_model=ReviewStatsOut)
async def stats_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("reviews.read")),
) -> ReviewStatsOut:
    data = await stats(db)
    return ReviewStatsOut(**data)


@router.get("", response_model=ReviewListResponse)
async def list_endpoint(
    source: Optional[str] = Query(default=None, max_length=32),
    rating: Optional[int] = Query(default=None, ge=1, le=5),
    status_: Optional[ReviewStatus] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("reviews.read")),
) -> ReviewListResponse:
    rows, total = await list_reviews(
        db,
        source=source,
        rating=rating,
        status_filter=status_,
        page=page,
        size=size,
    )
    return ReviewListResponse(
        items=[ReviewOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "", response_model=ReviewOut, status_code=status.HTTP_201_CREATED
)
async def create_endpoint(
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("reviews.write")),
) -> ReviewOut:
    review = await create_review(
        db, org_id=user.org_id, user_id=user.id, payload=payload
    )
    return ReviewOut.model_validate(review)


@router.get("/{review_id}", response_model=ReviewOut)
async def get_endpoint(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("reviews.read")),
) -> ReviewOut:
    review = await get_review(db, review_id)
    return ReviewOut.model_validate(review)


@router.patch("/{review_id}", response_model=ReviewOut)
async def update_endpoint(
    review_id: uuid.UUID,
    payload: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("reviews.write")),
) -> ReviewOut:
    review = await update_review(db, review_id=review_id, payload=payload)
    return ReviewOut.model_validate(review)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("reviews.write")),
) -> Response:
    await delete_review(db, review_id=review_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{review_id}/reply", response_model=ReviewOut)
async def reply_endpoint(
    review_id: uuid.UUID,
    payload: ReviewReplyPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("reviews.write")),
) -> ReviewOut:
    review = await reply_to_review(
        db, review_id=review_id, user_id=user.id, payload=payload
    )
    return ReviewOut.model_validate(review)


@router.post("/{review_id}/escalate", response_model=ReviewOut)
async def escalate_endpoint(
    review_id: uuid.UUID,
    payload: ReviewEscalatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("reviews.write")),
) -> ReviewOut:
    review = await escalate_review(
        db, review_id=review_id, user_id=user.id, payload=payload
    )
    return ReviewOut.model_validate(review)
