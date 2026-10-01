"""Data-access layer for the reviews module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations:

  * Reviews (``tbl_reviews``)
      get_review_by_id, list_reviews_query, insert_review,
      delete_review_row
  * Stats (drives the Reviews dashboard cards + chart)
      count_total_reviews, avg_review_rating,
      review_rating_distribution, count_responded_reviews,
      count_pending_reviews, count_low_rating_reviews_since
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.reviews.models import Review, ReviewStatus
from src.app.shared.db.pagination import paginate


async def get_review_by_id(session: AsyncSession, review_id: uuid.UUID) -> Review | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(Review).where(Review.id == review_id))
    return result.scalar_one_or_none()


async def list_reviews_query(
    session: AsyncSession,
    *,
    source: str | None = None,
    rating: int | None = None,
    max_rating: int | None = None,
    status_filter: ReviewStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Review], int]:
    """Filtered paginated list, newest first. ``max_rating`` keeps
    reviews at or below that star count (the "needs attention" panel)."""
    filters: list[Any] = []
    if source is not None:
        filters.append(Review.source == source)
    if rating is not None:
        filters.append(Review.rating == rating)
    if max_rating is not None:
        filters.append(Review.rating <= max_rating)
    if status_filter is not None:
        filters.append(Review.status == status_filter)
    where = and_(*filters) if filters else None

    base = select(Review)
    if where is not None:
        base = base.where(where)
    base = base.order_by(Review.created_at.desc())
    return await paginate(session, base, page=page, size=size)


def insert_review(session: AsyncSession, review: Review) -> None:
    """Register an already-constructed Review for INSERT."""
    session.add(review)


async def delete_review_row(session: AsyncSession, review: Review) -> None:
    """Mark a Review row for DELETE. Caller commits."""
    await session.delete(review)


# --- Stats --------------------------------------------------------------


async def count_total_reviews(session: AsyncSession) -> int:
    """Total review count for the active tenant."""
    return int((await session.execute(select(func.count()).select_from(Review))).scalar_one() or 0)


async def avg_review_rating(session: AsyncSession) -> float | None:
    """Average rating across all reviews. ``None`` when the table is
    empty (caller defaults to 0.0)."""
    avg = (await session.execute(select(func.avg(Review.rating)))).scalar_one()
    return float(avg) if avg is not None else None


async def review_rating_distribution(
    session: AsyncSession,
) -> list[Row]:
    """``(rating, count)`` GROUP BY for the distribution chart,
    sorted ascending."""
    return list(
        (
            await session.execute(
                select(Review.rating, func.count(Review.id))
                .group_by(Review.rating)
                .order_by(Review.rating.asc())
            )
        ).all()
    )


async def count_responded_reviews(session: AsyncSession) -> int:
    """Reviews that actually received a reply. Escalated-but-unanswered
    reviews are not "responded" — counting them inflated the rate."""
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Review).where(Review.reply_text.is_not(None))
            )
        ).scalar_one()
        or 0
    )


async def count_pending_reviews(session: AsyncSession) -> int:
    """Reviews currently awaiting a reply."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Review)
                .where(Review.status == ReviewStatus.pending_reply)
            )
        ).scalar_one()
        or 0
    )


async def count_low_rating_reviews_since(session: AsyncSession, *, cutoff: datetime) -> int:
    """Number of reviews with ``rating <= 3`` since ``cutoff``.
    Drives the "alerts in the last 7 days" card."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Review)
                .where(Review.created_at >= cutoff)
                .where(Review.rating <= 3)
            )
        ).scalar_one()
        or 0
    )


__all__ = [
    "avg_review_rating",
    "count_low_rating_reviews_since",
    "count_pending_reviews",
    "count_responded_reviews",
    "count_total_reviews",
    "delete_review_row",
    "get_review_by_id",
    "insert_review",
    "list_reviews_query",
    "review_rating_distribution",
]
