"""Dead-letter helpers for Google Ads webhook processing.

`record_dlq` (writer) is provider-neutral and lives in the parent
`core.integrations.dlq` module — both Google (Step 3) and Meta
(Step 5) workers share it. This file re-exports it for backwards
compatibility with the Step-3 callers.

`replay_dlq` stays Google-specific because re-enqueue must call the
Google Celery task. Meta's replay (if/when added) lives in
`meta/dlq.py`.
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
    `google_ads`. Existing Step-3 callers see no change. New code
    should call `core.integrations.dlq.record_dlq` directly with an
    explicit `provider=` kwarg."""
    return await _record_dlq(
        session,
        provider=IntegrationProvider.google_ads,
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
                "Original integration was deleted — cannot replay. Reconnect the provider first."
            ),
        )

    # Import the task lazily so a cyclic import (tasks → service →
    # dlq → tasks) doesn't fire at module-load time.
    from src.app.core.integrations.google.tasks import process_google_lead

    process_google_lead.delay(str(row.integration_id), row.payload)

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
