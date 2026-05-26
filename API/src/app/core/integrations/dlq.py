"""Provider-neutral DLQ writer.

`record_dlq` accepts the provider as a parameter so both Google
(Step 3) and Meta (Step 5) writers share a single insertion path.
Provider-specific replay logic stays in each provider's subpackage
(`google/dlq.py`, `meta/dlq.py` if/when needed) because re-enqueue
needs to call the matching Celery task.

Always commits — callers are Celery workers with no other
transactional work to bundle. Emits `integration.webhook.dlq` so an
operator can grep `audit_logs` for delivery-failure spikes.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.models import (
    IntegrationDLQ,
    IntegrationProvider,
)


async def record_dlq(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
    org_id: uuid.UUID,
    integration_id: Optional[uuid.UUID],
    payload: dict[str, Any],
    error_message: str,
    retries_attempted: int = 0,
) -> IntegrationDLQ:
    """Insert one DLQ row tagged with the source provider. Payload is
    stored verbatim — ad-webhook bodies are small (few KB each) and
    forensic replay benefits from the raw envelope, not a normalised
    projection."""
    row = IntegrationDLQ(
        org_id=org_id,
        integration_id=integration_id,
        provider=provider,
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
            "provider": provider.value,
            "integration_id": (
                str(integration_id) if integration_id else None
            ),
            "error_message": error_message[:500],
            "retries_attempted": retries_attempted,
        },
    )
    return row


__all__ = ["record_dlq"]
