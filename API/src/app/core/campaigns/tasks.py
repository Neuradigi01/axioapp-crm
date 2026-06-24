"""Celery tasks for the campaigns engine — Step 3.5.14.

Two tasks:

  1. `send_campaign_chunk_task(campaign_id, contact_ids)` —
     wraps the existing async `dispatch_chunk` so the API request
     that calls `start` returns immediately while the per-contact
     POSTs happen on a worker. Transient errors (network timeouts)
     trigger exponential-backoff retries; permanent errors
     (`WhatsAppSendError`, validation failures) are caught inside
     `dispatch_chunk` and recorded as `CampaignMessage.failed` —
     no retry, since the next attempt would fail identically.

  2. `dispatch_scheduled_campaigns_task()` — beat task that polls
     every 60s for campaigns in `status='scheduled'` whose
     `schedule_at <= now()` and flips them to `running` + enqueues
     their pre-queued chunks. Worst-case drift is 60s, which is fine
     for marketing/transactional campaigns the operator has scheduled
     "at 10:00 AM" or similar; the simplicity of cron beats per-
     campaign delayed-task coordination.

Celery may be absent in dev. The `_shared_task` shim mirrors
`integrations.google.tasks` — `.delay()` becomes a no-op and the
synchronous async body is callable directly so dev smoke tests
exercise the full flow without a worker.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery absent in dev shells
    HAS_CELERY = False

    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

                def retry(self, exc=None, **_):
                    raise exc if exc else RuntimeError("retry called")

            return _Stub()

        return _wrap


logger = logging.getLogger(__name__)


# --- send_campaign_chunk -------------------------------------------------


@_shared_task(
    bind=True,
    name="src.app.core.campaigns.tasks.send_campaign_chunk",
    # Auto-retry on transient network/IO errors only. Meta 4xx
    # (`WhatsAppSendError`) is caught inside dispatch_chunk and
    # written to `CampaignMessage.failed` — no point retrying a
    # malformed payload or a permanently-rejected recipient.
    autoretry_for=(ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=5,
    retry_backoff_max=300,
    retry_jitter=True,
)
def send_campaign_chunk(
    self, campaign_id: str, contact_ids: list[str]
) -> dict[str, Any]:
    """Celery sync entrypoint. Bridges into the async dispatch_chunk."""
    try:
        return asyncio.run(
            _send_campaign_chunk_async(
                campaign_id=uuid.UUID(campaign_id),
                contact_ids=[uuid.UUID(c) for c in contact_ids],
            )
        )
    except (ConnectionError, TimeoutError) as exc:
        if HAS_CELERY:
            raise self.retry(exc=exc)
        raise


async def _send_campaign_chunk_async(
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> dict[str, Any]:
    """Async body — opens a session, sets tenant context from the
    campaign row, runs `dispatch_chunk`."""
    from src.app.core.campaigns.service import dispatch_chunk, get_campaign
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    async with async_session() as session:
        # Bypass-tenant lookup of the campaign so we can set the
        # context from its org_id before any RLS-scoped query runs.
        from src.app.core.campaigns.models import Campaign
        from sqlalchemy import text as sql_text

        row = (
            await session.execute(
                sql_text("SELECT org_id FROM tbl_campaigns WHERE id = :cid"),
                {"cid": campaign_id},
            )
        ).mappings().first()
        if row is None:
            return {"campaign_id": str(campaign_id), "status": "missing"}
        org_id = row["org_id"]

        token = set_context(RequestContext(org_id=org_id, user_id=None))
        try:
            await dispatch_chunk(
                session,
                campaign_id=campaign_id,
                contact_ids=contact_ids,
            )
        finally:
            reset_context(token)
        return {
            "campaign_id": str(campaign_id),
            "contact_count": len(contact_ids),
        }


# --- dispatch_scheduled_campaigns (beat) --------------------------------


@_shared_task(
    name="src.app.core.campaigns.tasks.dispatch_scheduled_campaigns",
)
def dispatch_scheduled_campaigns() -> dict[str, Any]:
    """Beat-driven sweep — find scheduled campaigns whose `schedule_at`
    has elapsed, transition them to running, and fan out the chunk
    sends as Celery tasks.

    Runs every 60s. Worst-case firing drift is one minute, acceptable
    for marketing/transactional schedules that operators set to
    minute-granularity ("10:00 AM"). Tighter than that would call for
    per-campaign delayed `apply_async(eta=...)`, which trades simpler
    ops for the per-edit task re-issue burden.

    Returns the count of campaigns picked up; the value is mostly for
    logging/observability — Celery itself doesn't act on it."""
    return asyncio.run(_dispatch_scheduled_campaigns_async())


async def _dispatch_scheduled_campaigns_async() -> dict[str, Any]:
    from src.app.core.campaigns.models import Campaign, CampaignStatus
    from src.app.core.campaigns.service import dispatch_chunk
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session
    from sqlalchemy import text as sql_text

    fired = 0
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # Bypass-tenant scan — beat has no org context. We pick the
        # campaign id + org_id, then re-enter per-campaign with the
        # right context for `dispatch_chunk` to see RLS-scoped rows.
        rows = (
            await session.execute(
                sql_text(
                    """
                    SELECT id, org_id
                    FROM tbl_campaigns
                    WHERE status = 'scheduled'
                      AND schedule_at IS NOT NULL
                      AND schedule_at <= :now
                    ORDER BY schedule_at ASC
                    LIMIT 100
                    """
                ),
                {"now": now},
            )
        ).mappings().all()

        for row in rows:
            campaign_id = row["id"]
            org_id = row["org_id"]
            token = set_context(RequestContext(org_id=org_id, user_id=None))
            try:
                # Re-fetch under RLS context so we don't bypass tenancy
                # for the write.
                campaign = (
                    await session.execute(
                        select(Campaign).where(Campaign.id == campaign_id)
                    )
                ).scalar_one_or_none()
                if campaign is None:
                    continue

                # Pull queued contact ids for this campaign and chunk.
                from src.app.core.campaigns.models import CampaignMessage

                queued_rows = (
                    await session.execute(
                        select(CampaignMessage.contact_id).where(
                            CampaignMessage.campaign_id == campaign_id
                        )
                    )
                ).scalars().all()
                if not queued_rows:
                    campaign.status = CampaignStatus.done
                    await session.commit()
                    continue

                campaign.status = CampaignStatus.running
                await session.commit()

                # Chunk + dispatch. In CELERY_ENABLED prod the chunks
                # go through `.delay(...)` so the beat worker doesn't
                # block on Meta latency; eager mode runs inline.
                from src.app.core.campaigns.service import CHUNK_SIZE

                chunks = [
                    queued_rows[i : i + CHUNK_SIZE]
                    for i in range(0, len(queued_rows), CHUNK_SIZE)
                ]
                for chunk in chunks:
                    if HAS_CELERY:
                        send_campaign_chunk.delay(
                            str(campaign_id),
                            [str(c) for c in chunk],
                        )
                    else:
                        await dispatch_chunk(
                            session,
                            campaign_id=campaign_id,
                            contact_ids=chunk,
                        )
                fired += 1
            except Exception:
                logger.exception(
                    "scheduled campaign dispatch failed",
                    extra={"campaign_id": str(campaign_id)},
                )
            finally:
                reset_context(token)

    return {"fired": fired, "checked_at": now.isoformat()}


# whatsapp-platform-upgrade Step 29 — A/B winner decider.
# Runs `winner_holdback_hours` after the A/B campaign's dispatch
# completes. Picks the winning variant, persists it, + lets the
# next chunk pick up the winning template via the dispatch-time
# lookup in `service.dispatch_chunk` (a re-queue of the campaign
# is the cheap way to ship the winning template to any contacts
# the operator added post-hoc — for the v1 the audience is
# resolved up-front at start, so the decider's persistence is the
# only behaviour change).
@_shared_task(
    name="campaigns.run_ab_decision",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def run_ab_decision(self: Any, campaign_id: str) -> dict[str, Any]:
    """Pick the A/B winner for ``campaign_id``. Idempotent — the
    decider no-ops when ``winning_variant`` is already set, so a
    re-run after a worker crash doesn't double-flip.

    Returns a summary dict with the chosen variant + per-variant
    metric breakdown so the Celery flower task log captures the
    decision context."""

    async def _run() -> dict[str, Any]:
        from src.app.shared.db import async_session
        from src.app.shared.context import RequestContext, reset_context, set_context
        from src.app.core.campaigns.ab_decider import decide_winner
        from src.app.core.campaigns.models import Campaign

        cid = uuid.UUID(campaign_id)
        async with async_session() as session:
            # Resolve org from the campaign so RLS-scoped writes land
            # in the right tenant. We skip RLS by bypassing the
            # context — the decider lookup uses the explicit
            # `campaign_id` filter as the tenant gate.
            row = (
                await session.execute(
                    select(Campaign).where(Campaign.id == cid)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"decided": False, "reason": "campaign_not_found"}
            token = set_context(
                RequestContext(org_id=row.org_id, user_id=None)
            )
            try:
                decision = await decide_winner(session, campaign_id=cid)
            finally:
                reset_context(token)
        if decision is None:
            return {"decided": False, "reason": "no_decision"}
        return {
            "decided": True,
            "winning_variant": decision.winning_variant,
            "metric": decision.metric,
            "a_rate": decision.a.rate,
            "b_rate": decision.b.rate,
            "a_samples": decision.a.samples,
            "b_samples": decision.b.samples,
        }

    return asyncio.run(_run())


__all__ = [
    "HAS_CELERY",
    "dispatch_scheduled_campaigns",
    "run_ab_decision",
    "send_campaign_chunk",
]
