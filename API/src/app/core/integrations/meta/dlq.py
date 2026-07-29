"""Dead-letter helpers for Meta (Facebook + Instagram) webhook
processing.

Mirror of :mod:`src.app.core.integrations.google.dlq` for the Meta
provider. Structured as a thin provider-specific writer plus a
replay dispatcher that re-enqueues the row's payload through
``core.integrations.meta.tasks.process_meta_lead`` (the same Celery
task the webhook receiver enqueues on live traffic).

Was previously a checklist gap (Review Item I.52): the shared DLQ
list surfaced Meta failures alongside Google, but the ``Replay`` UI
button 400'd for anything whose ``provider`` was not ``google_ads``.
This module unblocks that.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.dlq import record_dlq as _record_dlq
from src.app.core.integrations.models import (
    IntegrationDLQ,
    IntegrationProvider,
)
from src.app.core.integrations.service import get_dlq

logger = logging.getLogger(__name__)


async def record_dlq(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID | None,
    payload: dict,
    error_message: str,
    retries_attempted: int = 0,
) -> IntegrationDLQ:
    """Provider-neutral writer with the provider pre-filled to
    ``meta_ads``. Mirrors :func:`google.dlq.record_dlq`. New code
    should call :func:`core.integrations.dlq.record_dlq` directly with
    an explicit ``provider=`` kwarg."""
    return await _record_dlq(
        session,
        provider=IntegrationProvider.meta_ads,
        org_id=org_id,
        integration_id=integration_id,
        payload=payload,
        error_message=error_message,
        retries_attempted=retries_attempted,
    )


async def replay_dlq(
    session: AsyncSession,
    *,
    dlq_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> IntegrationDLQ:
    """Re-enqueue a Meta DLQ payload through ``process_meta_lead``.

    Semantics match the Google path:

    - 404 if the row is missing.
    - 400 if the row's provider isn't ``meta_ads`` (caller mis-routed;
      point them at the Google replay endpoint).
    - 409 if the original ``tbl_integrations`` row is gone (nothing
      left to deliver into — operator must reconnect the provider
      before the payload can be re-processed).

    The DLQ row is marked replayed (``replayed_at``, ``replayed_by``)
    but not deleted — the same audit-trail convention Google uses so
    an operator can see what was retried, when, and by whom.

    Meta-specific caveats worth calling out to future maintainers:

    - Meta long-lived tokens can be up to 60 days old. If the stored
      access token has since expired the re-enqueued task will hit
      ``MetaTokenExpiredError`` and re-DLQ; the operator will see a
      new row and needs to reconnect the integration before the
      original event can land. That behaviour is intentional (better
      than silently dropping the lead) and matches how the live
      webhook path behaves under the same conditions.
    - The payload dict is whatever ``_enqueue_leadgen_changes`` /
      ``_enqueue_messaging_events`` put on the queue — page_id,
      leadgen_id, form_id, ad_id, campaign_id, created_time. The
      task decides how to re-materialise the lead from those; no
      transformation happens here.
    """
    row = await get_dlq(session, dlq_id=dlq_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DLQ row not found",
        )
    if row.provider != IntegrationProvider.meta_ads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"DLQ row provider is {row.provider.value}; use the "
                f"matching provider's replay endpoint."
            ),
        )
    if row.integration_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Original integration was deleted — cannot replay. "
                "Reconnect the Meta integration first."
            ),
        )

    # Lazy import to keep the module load acyclic (tasks → service →
    # dlq → tasks). Same pattern the Google DLQ uses.
    from src.app.core.integrations.meta.tasks import process_meta_lead

    process_meta_lead.delay(row.payload)

    row.replayed_at = datetime.now(UTC)
    row.replayed_by = actor_id
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.webhook.replayed",
        entity_type="integration_dlq",
        entity_id=row.id,
        after={"provider": row.provider.value},
    )
    return row


__all__ = ["record_dlq", "replay_dlq"]
