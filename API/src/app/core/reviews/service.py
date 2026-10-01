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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.reviews import data_access as _da
from src.app.core.reviews.models import Review, ReviewStatus
from src.app.core.reviews.schemas import (
    ReviewCreate,
    ReviewEscalatePayload,
    ReviewReplyPayload,
    ReviewUpdate,
)
from src.app.shared.audit import log_entity_change
from src.app.shared.db.queries import ensure_found

# --- reads ----------------------------------------------------------------


async def list_reviews(
    session: AsyncSession,
    *,
    source: str | None = None,
    rating: int | None = None,
    max_rating: int | None = None,
    status_filter: ReviewStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Review], int]:
    return await _da.list_reviews_query(
        session,
        source=source,
        rating=rating,
        max_rating=max_rating,
        status_filter=status_filter,
        page=page,
        size=size,
    )


async def get_review(session: AsyncSession, review_id: uuid.UUID) -> Review:
    return ensure_found(await _da.get_review_by_id(session, review_id), entity="review")


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
    _da.insert_review(session, review)
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


async def delete_review(session: AsyncSession, *, review_id: uuid.UUID) -> None:
    review = await get_review(session, review_id)
    before = _snapshot(review)
    await _da.delete_review_row(session, review)
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
    review.replied_at = datetime.now(UTC)
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
    await _publish_review_lifecycle_event(
        session=session,
        review=review,
        event_type="review.replied",
        extras={"reply_preview": payload.text[:160]},
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
    await _publish_review_lifecycle_event(
        session=session,
        review=review,
        event_type="review.escalated",
        extras={"reason": payload.reason},
    )
    return review


async def _publish_review_lifecycle_event(
    *,
    session: AsyncSession,
    review: Review,
    event_type: str,
    extras: dict[str, Any] | None = None,
) -> None:
    """Publish a ``review.<verb>`` event (``tasks/automation-conditions/``
    follow-up — review.replied for customer acknowledgement /
    review.escalated for manager alerts).

    Same fire-and-forget try/except pattern as the other lifecycle
    publishers. Event-id ``<slug>:{review.id}`` deduplicates on
    retry — a review only gets one "first replied" and one "first
    escalated" event fire regardless of subsequent edits.
    """
    try:
        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        contact = None
        if review.contact_id is not None:
            contact = (
                await session.execute(_select(Contact).where(Contact.id == review.contact_id))
            ).scalar_one_or_none()
        org = (
            await session.execute(_select(Organization).where(Organization.id == review.org_id))
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "review_id": str(review.id),
            "contact_id": str(review.contact_id) if review.contact_id else None,
            "rating": review.rating,
            "review": {
                "id": str(review.id),
                "rating": review.rating,
                "status": review.status.value,
                "source": review.source,
            },
        }
        if extras:
            payload.update(extras)
            payload["review"].update(extras)
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        slug = event_type.replace(".", "_")
        await events_publish(
            event_type,
            payload,
            org_id=review.org_id,
            event_id=f"{slug}:{review.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "reviews publish_%s_failed org=%s review=%s",
            event_type.replace(".", "_"),
            review.org_id,
            review.id,
        )


# Suggested replies: business-owner voice, platform-safe length.
_SUGGEST_REPLY_SYSTEM = (
    "You write public replies from a business to its customer reviews. "
    "Thank the reviewer, address what they actually said, stay warm and "
    "professional, and keep it under 600 characters. For a negative review "
    "apologise without admitting fault on specifics, and invite them to get in "
    "touch so the team can make it right. Never invent offers, refunds or "
    "facts. Reply in the reviewer's language. Return only the reply text."
)


async def suggest_review_reply(
    session: AsyncSession, *, review_id: uuid.UUID, org_id: uuid.UUID
) -> str:
    """Draft a public reply with the org's AI Assistant (shared key +
    budget path from the conversations module). Nothing is posted."""
    from src.app.core.conversations.ai_assist_service import complete_with_org_assistant

    review = await get_review(session, review_id)
    review_text = (review.text or "").strip() or "(rating only, no written review)"
    user_prompt = (
        f"Platform: {review.source}\n"
        f"Rating: {review.rating} out of 5\n"
        f"Review: {review_text[:2000]}\n\n"
        "Write the business's reply."
    )
    return await complete_with_org_assistant(
        session,
        org_id=org_id,
        channel=None,
        system=_SUGGEST_REPLY_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=300,
        include_business_context=True,
    )


# --- stats ----------------------------------------------------------------


async def stats(session: AsyncSession) -> dict[str, Any]:
    total = await _da.count_total_reviews(session)

    if total == 0:
        return {
            "total": 0,
            "average_rating": 0.0,
            "response_rate_pct": 0.0,
            "distribution": [],
            "pending_count": 0,
            "alerts_last_7_days": 0,
            "status_counts": {},
            "source_counts": {},
        }

    avg = await _da.avg_review_rating(session)
    avg = avg if avg is not None else 0.0

    dist_rows = await _da.review_rating_distribution(session)
    distribution = [{"rating": int(r.rating), "count": int(r[1])} for r in dist_rows]

    responded = await _da.count_responded_reviews(session)
    response_rate = (responded / total) * 100 if total else 0.0

    pending = await _da.count_pending_reviews(session)

    cutoff = datetime.now(UTC) - timedelta(days=7)
    alerts = await _da.count_low_rating_reviews_since(session, cutoff=cutoff)

    return {
        "total": int(total),
        "average_rating": round(avg, 2),
        "response_rate_pct": round(response_rate, 2),
        "distribution": distribution,
        "pending_count": int(pending),
        "alerts_last_7_days": int(alerts),
        "status_counts": await _da.review_status_counts(session),
        "source_counts": await _da.review_source_counts(session),
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
