"""Dead-letter helpers for Google Ads webhook processing.

A payload lands in `integration_dlq` when:

  - the inbound integration is disconnected / missing
  - no `integration_subscriptions` row matches the payload's `form_id`
  - the Celery task exhausts its retry budget on a transient error
  - lead-creation fails with a validation error the worker can't recover

Replay re-enqueues the original payload through the same task. It
does NOT delete the DLQ row — `replayed_at` flips so the Settings UI
can show "replayed at X, see lead Y" without losing forensic trail.

The Meta side (Step 5) shares the same DLQ table but the Meta-specific
re-enqueue lives in `meta/dlq.py`. This module stays Google-only so
each provider's replay path is independently testable.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
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
    integration_id: Optional[uuid.UUID],
    payload: dict[str, Any],
    error_message: str,
    retries_attempted: int = 0,
) -> IntegrationDLQ:
    """Insert one DLQ row. Always commits — the caller is in the Celery
    worker and has no other transactional work to bundle. Emits
    `integration.webhook.dlq` audit so an operator can grep for spikes.

    `payload` is stored verbatim — Google's body is small (a few KB)
    and forensic replay benefits from the raw shape, not a normalised
    one."""
    row = IntegrationDLQ(
        org_id=org_id,
        integration_id=integration_id,
        provider=IntegrationProvider.google_ads,
        payload=payload,
        error_message=error_message[:2000],
        retries_attempted=retries_attempted,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.webhook.dlq",
        entity_type="integration_dlq",
        entity_id=row.id,
        after={
            "provider": IntegrationProvider.google_ads.value,
            "integration_id": (
                str(integration_id) if integration_id else None
            ),
            "error_message": error_message[:500],
            "retries_attempted": retries_attempted,
        },
    )
    return row


async def replay_dlq(
    session: AsyncSession,
    *,
    dlq_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
) -> IntegrationDLQ:
    """Re-enqueue a DLQ payload through `process_google_lead`. Marks
    the row as replayed (does NOT delete). Raises 404 if the row is
    missing, 409 if the linked integration is gone (no target to
    deliver into)."""
    row = await get_dlq(session, dlq_id=dlq_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DLQ row not found",
        )
    if row.provider != IntegrationProvider.google_ads:
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
                "Reconnect the provider first."
            ),
        )

    # Import the task lazily so a cyclic import (tasks → service →
    # dlq → tasks) doesn't fire at module-load time.
    from src.app.core.integrations.google.tasks import process_google_lead

    process_google_lead.delay(
        str(row.integration_id), row.payload
    )

    row.replayed_at = datetime.now(timezone.utc)
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
