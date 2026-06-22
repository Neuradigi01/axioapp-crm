"""Phone-health snapshot + event-log service
(whatsapp-platform-upgrade Step 12).

Three jobs:

  * :func:`refresh_from_meta` — pull the per-number health fields
    Meta exposes on ``GET /{phone_id}?fields=...`` and diff against
    the cached row. Every changed field (quality, tier, name_status,
    restrictions) writes one row to
    ``tbl_whatsapp_phone_health_events`` so the timeline chart has
    something to render. Idempotent — re-running with no changes
    writes no events.

  * :func:`apply_webhook_quality_event` — handle the
    ``phone_number_quality_update`` webhook field. Same diff path so
    a webhook arriving before the next refresh tick keeps the cache
    fresh AND drops a timeline row.

  * :func:`get_phone_health` — aggregate read for the card + widget.
    Wraps the cached snapshot + last-30-days event log + the existing
    Step-3.5.16 send-capacity numbers (no duplication of that math).

Recovery-checklist keys are computed here so the frontend stays dumb:
  * ``quality_degraded`` — quality_rating is YELLOW or RED
  * ``restricted``       — restrictions list is non-empty
  * ``name_status_pending`` — Meta hasn't approved the verified name yet
  * ``low_tier``         — tier is TIER_50 or TIER_250 (room to grow)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import (
    WhatsAppAccountConfig,
    WhatsAppPhoneHealthEvent,
    WhatsAppPhoneHealthEventType,
)
from src.app.core.integrations.whatsapp.status import (
    TIER_LABELS,
    TIER_LIMITS,
    _count_unique_recipients_today,
)

logger = logging.getLogger(__name__)


HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15.0)


_PHONE_HEALTH_FIELDS = (
    "quality_rating,messaging_limit_tier,name_status,"
    "code_verification_status,throughput,is_official_business_account"
)


# --- Meta calls -----------------------------------------------------------


async def _fetch_phone_health(
    *,
    phone_id: str,
    token: str,
    api_version: str,
    http_client_factory: HttpClientFactory,
) -> dict[str, Any]:
    """`GET /{phone_id}?fields=...` returns one flat dict — we pass it
    back verbatim. Throws `WhatsAppNotConnected` mirroring the
    capacity-lookup path so the router maps everything to 409
    consistently."""
    url = (
        f"https://graph.facebook.com/{api_version}/{phone_id}"
        f"?fields={_PHONE_HEALTH_FIELDS}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    async with http_client_factory() as client:
        response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        raise WhatsAppNotConnected(
            f"Meta API rejected the phone-health lookup: "
            f"{_extract_meta_error(response)}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise WhatsAppNotConnected(
            f"Unexpected Meta response shape: {body!r}"
        )
    return body


def _extract_meta_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
    return f"HTTP {response.status_code}: {response.text[:200]}"


# --- diff + event writes -------------------------------------------------


def _diff_fields(
    *,
    config: WhatsAppAccountConfig,
    new_quality: Optional[str],
    new_tier: Optional[str],
    new_name_status: Optional[str],
    new_throughput: Optional[int],
    new_restrictions: Optional[list[dict[str, Any]]],
) -> list[tuple[WhatsAppPhoneHealthEventType, Any, Any]]:
    """Build the list of (event_type, old, new) tuples for fields
    that actually changed. Returns an empty list when the cached row
    matches the new snapshot — keeps the refresh idempotent."""
    events: list[tuple[WhatsAppPhoneHealthEventType, Any, Any]] = []

    if new_quality and new_quality != config.quality_rating:
        events.append(
            (
                WhatsAppPhoneHealthEventType.quality_change,
                config.quality_rating,
                new_quality,
            )
        )

    if new_tier and new_tier != config.messaging_limit_tier:
        events.append(
            (
                WhatsAppPhoneHealthEventType.tier_change,
                config.messaging_limit_tier,
                new_tier,
            )
        )

    if new_name_status and new_name_status != config.name_status:
        events.append(
            (
                WhatsAppPhoneHealthEventType.name_status_change,
                config.name_status,
                new_name_status,
            )
        )

    # Restriction changes — treat the list as a set of restriction_type
    # values. New types added → restriction_added; types disappearing
    # → restriction_lifted (one event per direction is enough — the
    # operator just needs to know "something changed").
    old_restrictions = config.restrictions or []
    new_list = new_restrictions or []
    old_types = {
        r.get("restriction_type") for r in old_restrictions if isinstance(r, dict)
    }
    new_types = {
        r.get("restriction_type") for r in new_list if isinstance(r, dict)
    }
    if new_types - old_types:
        events.append(
            (
                WhatsAppPhoneHealthEventType.restriction_added,
                list(old_restrictions),
                list(new_list),
            )
        )
    elif old_types - new_types and not new_types:
        events.append(
            (
                WhatsAppPhoneHealthEventType.restriction_lifted,
                list(old_restrictions),
                list(new_list),
            )
        )

    return events


async def _write_events(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone_id: str,
    events: list[tuple[WhatsAppPhoneHealthEventType, Any, Any]],
    occurred_at: datetime,
) -> None:
    """Persist one row per (event_type, old, new) tuple. RLS scopes
    the insert via the existing `app.org_id` context."""
    for event_type, old_value, new_value in events:
        session.add(
            WhatsAppPhoneHealthEvent(
                org_id=org_id,
                phone_id=phone_id,
                event_type=event_type,
                old_value=(
                    {"value": old_value}
                    if not isinstance(old_value, (list, dict))
                    else old_value
                )
                if old_value is not None
                else None,
                new_value=(
                    {"value": new_value}
                    if not isinstance(new_value, (list, dict))
                    else new_value
                )
                if new_value is not None
                else None,
                occurred_at=occurred_at,
            )
        )
        await audit.log(
            f"integration.whatsapp.phone_health.{event_type.value}",
            entity_type="whatsapp_account",
            entity_id=None,
            before={"value": old_value} if old_value is not None else None,
            after={"value": new_value} if new_value is not None else None,
        )


# --- recovery checklist --------------------------------------------------


def _recovery_keys(
    *,
    quality_rating: Optional[str],
    name_status: Optional[str],
    restrictions: list[dict[str, Any]],
    tier: Optional[str],
) -> list[str]:
    """Operator-actionable hint keys for the UI. The frontend renders
    a fixed copy block per key; we only decide which to show."""
    keys: list[str] = []
    if quality_rating in ("YELLOW", "RED"):
        keys.append("quality_degraded")
    if restrictions:
        keys.append("restricted")
    if name_status and name_status not in ("APPROVED", "AVAILABLE_WITHOUT_REVIEW"):
        keys.append("name_status_pending")
    if tier in ("TIER_50", "TIER_250"):
        keys.append("low_tier")
    return keys


# --- public API ----------------------------------------------------------


async def refresh_from_meta(
    session: AsyncSession,
    *,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> WhatsAppAccountConfig:
    """One-shot Meta pull + diff + persist. Returns the refreshed
    config row. Raises ``WhatsAppNotConnected`` when the org has no
    integration (router maps to 409). New tier values get mirrored
    onto the existing ``messaging_limit_tier`` column so the Step-
    3.5.16 capacity banner stays consistent."""
    bundle = await get_active_config(session)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. "
            "Connect it in Settings → Integrations."
        )
    integration, config = bundle
    if integration.access_token_enc is None:
        raise WhatsAppNotConnected(
            "Stored credentials are missing; reconnect required."
        )
    token = decrypt(integration.access_token_enc)

    payload = await _fetch_phone_health(
        phone_id=config.phone_id,
        token=token,
        api_version=config.api_version,
        http_client_factory=http_client_factory,
    )

    new_quality = (
        str(payload.get("quality_rating") or "").upper() or None
    )
    new_tier = payload.get("messaging_limit_tier") or None
    new_name_status = payload.get("name_status") or None
    raw_throughput = payload.get("throughput")
    new_throughput: Optional[int] = None
    if isinstance(raw_throughput, dict):
        level = raw_throughput.get("level")
        if isinstance(level, int):
            new_throughput = level
    elif isinstance(raw_throughput, int):
        new_throughput = raw_throughput
    raw_restrictions = payload.get("restrictions")
    new_restrictions: list[dict[str, Any]] = []
    if isinstance(raw_restrictions, list):
        new_restrictions = [r for r in raw_restrictions if isinstance(r, dict)]

    diff = _diff_fields(
        config=config,
        new_quality=new_quality,
        new_tier=new_tier,
        new_name_status=new_name_status,
        new_throughput=new_throughput,
        new_restrictions=new_restrictions,
    )

    now = datetime.now(timezone.utc)
    if new_quality:
        config.quality_rating = new_quality
    if new_tier:
        config.messaging_limit_tier = new_tier
        config.tier_synced_at = now
    if new_name_status:
        config.name_status = new_name_status
    if new_throughput is not None:
        config.throughput = new_throughput
    config.restrictions = new_restrictions or None
    config.health_synced_at = now

    if diff:
        await _write_events(
            session,
            org_id=integration.org_id,
            phone_id=config.phone_id,
            events=diff,
            occurred_at=now,
        )

    await session.commit()
    await session.refresh(config)
    return config


async def apply_webhook_quality_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone_id: str,
    new_quality: Optional[str],
    new_tier: Optional[str],
    occurred_at: Optional[datetime] = None,
) -> bool:
    """Handle a ``phone_number_quality_update`` webhook event.

    Updates the cached row + drops a timeline event when the value
    actually changed. Idempotent on Meta retries: a webhook delivering
    the same quality rating twice writes one event the first time, a
    no-op the second.

    Returns True when a row was updated."""
    result = await session.execute(
        select(WhatsAppAccountConfig).where(
            WhatsAppAccountConfig.phone_id == phone_id,
            WhatsAppAccountConfig.org_id == org_id,
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        logger.info(
            "phone_number_quality_update: no config matched phone_id=%s",
            phone_id,
        )
        return False

    diff = _diff_fields(
        config=config,
        new_quality=(new_quality.upper() if new_quality else None),
        new_tier=new_tier,
        new_name_status=None,
        new_throughput=None,
        new_restrictions=None,
    )
    if not diff:
        return False

    timestamp = occurred_at or datetime.now(timezone.utc)
    if new_quality:
        config.quality_rating = new_quality.upper()
    if new_tier:
        config.messaging_limit_tier = new_tier
        config.tier_synced_at = timestamp
    config.health_synced_at = timestamp

    await _write_events(
        session,
        org_id=org_id,
        phone_id=phone_id,
        events=diff,
        occurred_at=timestamp,
    )
    await session.commit()
    return True


async def get_phone_health(
    session: AsyncSession,
    *,
    timeline_days: int = 30,
) -> dict[str, Any]:
    """Build the read-shape consumed by the phone-health card + the
    dashboard widget. Reads the cached row + last-N-days event log;
    callers can trigger a fresh Meta pull via the explicit refresh
    endpoint."""
    bundle = await get_active_config(session)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. "
            "Connect it in Settings → Integrations."
        )
    integration, config = bundle

    tier = config.messaging_limit_tier
    tier_label = TIER_LABELS.get(tier or "", tier) if tier else None
    daily_limit = TIER_LIMITS.get(tier or "", 0) if tier else 0
    used = await _count_unique_recipients_today(session)
    is_unlimited = daily_limit == -1
    if is_unlimited:
        remaining = -1
        usage_percent = 0
    elif daily_limit > 0:
        remaining = max(0, daily_limit - used)
        usage_percent = min(round(used / daily_limit * 100), 100)
    else:
        remaining = 0
        usage_percent = 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=timeline_days)
    events_rows = (
        (
            await session.execute(
                select(WhatsAppPhoneHealthEvent)
                .where(WhatsAppPhoneHealthEvent.phone_id == config.phone_id)
                .where(WhatsAppPhoneHealthEvent.occurred_at >= cutoff)
                .order_by(WhatsAppPhoneHealthEvent.occurred_at.asc())
                .limit(500)
            )
        ).scalars().all()
    )

    return {
        "phone_id": config.phone_id,
        "display_phone_number": config.display_phone_number,
        "verified_name": config.verified_name,
        "quality_rating": (config.quality_rating or "UNKNOWN").upper(),
        "messaging_limit_tier": config.messaging_limit_tier,
        "tier_label": tier_label,
        "name_status": config.name_status,
        "throughput": config.throughput,
        "restrictions": list(config.restrictions or []),
        "health_synced_at": config.health_synced_at,
        "daily_limit": max(daily_limit, 0) if not is_unlimited else -1,
        "used_today": used,
        "remaining": remaining,
        "usage_percent": usage_percent,
        "is_unlimited": is_unlimited,
        "recovery_keys": _recovery_keys(
            quality_rating=config.quality_rating,
            name_status=config.name_status,
            restrictions=list(config.restrictions or []),
            tier=config.messaging_limit_tier,
        ),
        "events": [
            {
                "id": e.id,
                "phone_id": e.phone_id,
                "event_type": e.event_type.value,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "occurred_at": e.occurred_at,
                "recorded_at": e.recorded_at,
            }
            for e in events_rows
        ],
    }


__all__ = [
    "apply_webhook_quality_event",
    "get_phone_health",
    "refresh_from_meta",
]
