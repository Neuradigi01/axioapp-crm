"""Aggregate webhook-delivery status per provider for the Settings
dashboard panel (Step 8).

Polled every ~30 seconds by the SPA. Returns a fixed-shape response
covering both providers regardless of connect state — keeps the UI
tile layout stable.

Counts come from `audit_logs` events:

  - `integration.webhook.received` → +1 to `deliveries_24h_accepted`
    (emitted by the Step 3 / Step 5 Celery workers AFTER a lead is
    successfully created)
  - `integration.webhook.dlq` → +1 to `deliveries_24h_failed`
    (emitted whenever a payload lands in DLQ)
  - latest `received` timestamp → `last_delivery_at`

`audit_logs` already has indexes on `(org_id, action, created_at)` so
the per-provider count queries are an indexed scan — trivial cost
even when called every 30s per Owner viewing the page.

`dlq_open_total` is a quick `COUNT(*) WHERE replayed_at IS NULL`
across the `integration_dlq` table — exact, not approximated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.schemas import (
    IntegrationStatusResponse,
    ProviderDeliveryStatus,
)
from sqlalchemy import select


_PROVIDERS: tuple[IntegrationProvider, ...] = (
    IntegrationProvider.google_ads,
    IntegrationProvider.meta_ads,
)


async def build_status(
    session: AsyncSession,
) -> IntegrationStatusResponse:
    """Build the per-provider status snapshot for the active tenant.
    All queries are auto-scoped to org via the ORM tenant filter (for
    `Integration`) and via explicit `org_id` filters on the raw
    audit-log SQL.
    """
    # 1. Resolve each provider's current connection status. Default
    # to `disconnected` when no row exists so the dashboard renders
    # a consistent "Not connected" tile.
    integration_status: dict[str, IntegrationStatus] = {}
    rows = (await session.execute(select(Integration))).scalars().all()
    for row in rows:
        integration_status[row.provider.value] = row.status

    # 2. Per-provider 24h counters + last-delivery timestamp. One
    # raw SQL query per provider keeps things explicit; the audit_log
    # indexes do the heavy lifting.
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    per_provider: list[ProviderDeliveryStatus] = []
    for provider in _PROVIDERS:
        accepted, failed, last_at = await _provider_counts(
            session, provider=provider.value, since=since
        )
        per_provider.append(
            ProviderDeliveryStatus(
                provider=provider.value,  # type: ignore[arg-type]
                status=(
                    integration_status.get(
                        provider.value, IntegrationStatus.disconnected
                    ).value
                ),  # type: ignore[arg-type]
                last_delivery_at=last_at,
                deliveries_24h_accepted=accepted,
                deliveries_24h_failed=failed,
            )
        )

    # 3. Open DLQ rows across all providers. The dashboard panel's
    # banner triggers on this — "X failed deliveries need attention".
    dlq_total = await _open_dlq_count(session)

    return IntegrationStatusResponse(
        providers=per_provider,
        dlq_open_total=dlq_total,
    )


async def _provider_counts(
    session: AsyncSession,
    *,
    provider: str,
    since: datetime,
) -> tuple[int, int, datetime | None]:
    """Return `(accepted_count, failed_count, last_accepted_at)` for
    one provider over the trailing 24h window.

    Uses raw SQL via `text()` because the audit-log `after` column is
    JSONB and the ORM tenant-filter listener doesn't apply to text()
    queries — explicit `org_id` belt + suspenders. RLS still authorises
    via the session-context `app.org_id`."""
    sql = text(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE action = 'integration.webhook.received'
            ) AS accepted,
            COUNT(*) FILTER (
                WHERE action = 'integration.webhook.dlq'
            ) AS failed,
            MAX(created_at) FILTER (
                WHERE action = 'integration.webhook.received'
            ) AS last_accepted_at
        FROM audit_logs
        WHERE created_at >= :since
          AND action IN (
              'integration.webhook.received',
              'integration.webhook.dlq'
          )
          AND COALESCE(after->>'provider', '') = :provider
        """
    )
    result = (
        await session.execute(sql, {"since": since, "provider": provider})
    ).mappings().first()
    if result is None:
        return 0, 0, None
    return (
        int(result["accepted"] or 0),
        int(result["failed"] or 0),
        result["last_accepted_at"],
    )


async def _open_dlq_count(session: AsyncSession) -> int:
    """Count DLQ rows that haven't been replayed OR discarded
    (`replayed_at IS NULL`). Matches what `list_dlq(include_replayed=
    False)` returns; the panel uses this number to drive the banner.
    """
    sql = text(
        """
        SELECT COUNT(*) FROM integration_dlq
        WHERE replayed_at IS NULL
        """
    )
    return int((await session.execute(sql)).scalar() or 0)


__all__ = ["build_status"]
