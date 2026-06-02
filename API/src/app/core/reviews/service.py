"""Service layer for the reviews module.

Five concerns:

1. CRUD over `Review`.
2. `reply` — sets `reply_text`, `replied_at`, `replied_by_id`, flips
   `status` → `replied`.
3. `escalate` — flips `status` → `escalated`. Audit captures the
   reason in the after-snapshot. The future Campaigns integration
   (Phase 5.6) will hook into this state.
4. Stats — distribution by rating, average, response rate (replied or
   escalated / total), pending count, alerts (≤3 stars in the last 7
   days).
5. Activity log — every new review tied to a contact records a `note`
   activity on the contact timeline (review.created), every reply
   records a `note` activity (review.replied). We use `note` because
   reviews aren't one of the bounded chat-style ActivityTypes.

All mutations fire `audit.log`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.reviews.models import Review, ReviewStatus
from src.app.core.reviews.schemas import (
    ReviewCreate,
    ReviewEscalatePayload,
    ReviewReplyPayload,
    ReviewUpdate,
)
from src.app.shared.audit import log_entity_change
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import get_or_404


# --- reads ----------------------------------------------------------------


async def list_reviews(
    session: AsyncSession,
    *,
    source: Optional[str] = None,
    rating: Optional[int] = None,
    status_filter: Optional[ReviewStatus] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Review], int]:
    filters: list[Any] = []
    if source is not None:
        filters.append(Review.source == source)
    if rating is not None:
        filters.append(Review.rating == rating)
    if status_filter is not None:
        filters.append(Review.status == status_filter)
    where = and_(*filters) if filters else None

    base = select(Review)
    if where is not None:
        base = base.where(where)
    base = base.order_by(Review.created_at.desc())

    return await paginate(session, base, page=page, size=size)


async def get_review(session: AsyncSession, review_id: uuid.UUID) -> Review:
    return await get_or_404(session, Review, review_id, entity="review")


# --- writes ---------------------------------------------------------------


async def create_review(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ReviewCreate,
) -> Review:
    review = Review(
        org_id=org_id,
        source=payload.source,
        source_id=payload.source_id,
        contact_id=payload.contact_id,
        rating=payload.rating,
        text=payload.text,
        tags=payload.tags,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)

    await log_entity_change(
        action="reviews.created",
        entity_type="review",
        entity_id=review.id,
        after=_snapshot(review),
    )
    if review.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=review.contact_id,
            type=ActivityType.note,
            payload={
                "kind": "review.created",
                "source": review.source,
                "rating": review.rating,
                "preview": (review.text or "")[:160],
                "review_id": str(review.id),
            },
            user_id=user_id,
            org_id=org_id,
        )
    return review


async def update_review(
    session: AsyncSession,
    *,
    review_id: uuid.UUID,
    payload: ReviewUpdate,
) -> Review:
    review = await get_review(session, review_id)
    before = _snapshot(review)
    changed = False
    if payload.source is not None:
        review.source = payload.source
        changed = True
    if payload.source_id is not None:
        review.source_id = payload.source_id
        changed = True
    if payload.contact_id is not None:
        review.contact_id = payload.contact_id
        changed = True
    if payload.rating is not None:
        review.rating = payload.rating
        changed = True
    if payload.text is not None:
        review.text = payload.text
        changed = True
    if payload.tags is not None:
        review.tags = payload.tags
        changed = True
    if changed:
        await session.commit()
        await session.refresh(review)
        await log_entity_change(
            action="reviews.updated",
            entity_type="review",
            entity_id=review.id,
            before=before,
            after=_snapshot(review),
        )
    return review


async def delete_review(
    session: AsyncSession, *, review_id: uuid.UUID
) -> None:
    review = await get_review(session, review_id)
    before = _snapshot(review)
    await session.delete(review)
    await session.commit()
    await log_entity_change(
        action="reviews.deleted",
        entity_type="review",
        entity_id=review_id,
        before=before,
    )


async def reply_to_review(
    session: AsyncSession,
    *,
    review_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ReviewReplyPayload,
) -> Review:
    review = await get_review(session, review_id)
    before = _snapshot(review)
    review.reply_text = payload.text
    review.replied_at = datetime.now(timezone.utc)
    review.replied_by_id = user_id
    review.status = ReviewStatus.replied
    await session.commit()
    await session.refresh(review)
    await audit.log(
        "reviews.replied",
        entity_type="review",
        entity_id=review.id,
        before=before,
        after=_snapshot(review),
    )
    if review.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=review.contact_id,
            type=ActivityType.note,
            payload={
                "kind": "review.replied",
                "preview": payload.text[:160],
                "review_id": str(review.id),
            },
            user_id=user_id,
            org_id=review.org_id,
        )
    return review


async def escalate_review(
    session: AsyncSession,
    *,
    review_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ReviewEscalatePayload,
) -> Review:
    review = await get_review(session, review_id)
    before = _snapshot(review)
    review.status = ReviewStatus.escalated
    await session.commit()
    await session.refresh(review)
    await audit.log(
        "reviews.escalated",
        entity_type="review",
        entity_id=review.id,
        before=before,
        after={**_snapshot(review), "reason": payload.reason},
        user_id=user_id,
    )
    return review


# --- stats ----------------------------------------------------------------


async def stats(session: AsyncSession) -> dict[str, Any]:
    total = (
        await session.execute(select(func.count()).select_from(Review))
    ).scalar_one() or 0

    if total == 0:
        return {
            "total": 0,
            "average_rating": 0.0,
            "response_rate_pct": 0.0,
            "distribution": [],
            "pending_count": 0,
            "alerts_last_7_days": 0,
        }

    avg = (
        await session.execute(select(func.avg(Review.rating)))
    ).scalar_one()
    avg = float(avg) if avg is not None else 0.0

    dist_rows = (
        await session.execute(
            select(Review.rating, func.count(Review.id))
            .group_by(Review.rating)
            .order_by(Review.rating.asc())
        )
    ).all()
    distribution = [
        {"rating": int(r.rating), "count": int(r[1])} for r in dist_rows
    ]

    responded = (
        await session.execute(
            select(func.count())
            .select_from(Review)
            .where(Review.status != ReviewStatus.pending_reply)
        )
    ).scalar_one() or 0
    response_rate = (responded / total) * 100 if total else 0.0

    pending = (
        await session.execute(
            select(func.count())
            .select_from(Review)
            .where(Review.status == ReviewStatus.pending_reply)
        )
    ).scalar_one() or 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    alerts = (
        await session.execute(
            select(func.count())
            .select_from(Review)
            .where(Review.created_at >= cutoff)
            .where(Review.rating <= 3)
        )
    ).scalar_one() or 0

    return {
        "total": int(total),
        "average_rating": round(avg, 2),
        "response_rate_pct": round(response_rate, 2),
        "distribution": distribution,
        "pending_count": int(pending),
        "alerts_last_7_days": int(alerts),
    }


# --- helpers --------------------------------------------------------------


def _snapshot(r: Review) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "source": r.source,
        "source_id": r.source_id,
        "contact_id": str(r.contact_id) if r.contact_id else None,
        "rating": r.rating,
        "status": r.status.value,
    }


__all__ = [
    "create_review",
    "delete_review",
    "escalate_review",
    "get_review",
    "list_reviews",
    "reply_to_review",
    "stats",
    "update_review",
]
