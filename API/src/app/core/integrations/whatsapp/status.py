"""WhatsApp send-capacity service — Meta tier + today's used quota.

Powers the "WhatsApp quota: 7,153 remaining today" banner the campaign
create modal shows the operator (Step 3.5.16). One responsibility:
take a session, return a snapshot of how many more unique recipients
this org can safely WhatsApp before tripping Meta's daily cap.

Tier comes from Meta — `GET /{phone_id}?fields=messaging_limit_tier`
— and is cached on `WhatsAppAccountConfig.messaging_limit_tier` for
one hour to keep the Graph-API call rate negligible. The hourly TTL
matches the cadence at which a number can actually move tiers (Meta
re-evaluates over rolling 7-day windows, so a finer cache buys no
freshness, only API cost).

Used-today comes from local DB — `COUNT(DISTINCT conversation_id)`
over outbound WhatsApp messages in the last 24 hours. This matches
Meta's tier accounting unit ("unique customers per rolling 24h"),
NOT total message count. Sending the same contact 50 messages in a
day still counts as 1 toward the tier limit.

The plaintext bearer token is decrypted inside `_get_tier_cached`'s
call frame only — same contract as `templates.sync_templates`. Never
logged, never returned to the API surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
    MessageDirection,
)
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig

logger = logging.getLogger(__name__)


HttpClientFactory = Callable[[], httpx.AsyncClient]


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0)


# Meta's published daily-recipient caps per tier. `-1` is the sentinel
# for "unlimited" — the API surface translates this to `remaining: -1`
# and the UI hides the progress bar. Source: developers.facebook.com
# /docs/whatsapp/cloud-api/messages/throughput
TIER_LIMITS: dict[str, int] = {
    "TIER_50": 50,
    "TIER_250": 250,
    "TIER_1K": 1_000,
    "TIER_10K": 10_000,
    "TIER_100K": 100_000,
    "TIER_UNLIMITED": -1,
}

# Operator-friendly labels for the banner. Hindi-style number grouping
# ("1 lakh") is intentional — the product is India-only (CLAUDE.md).
TIER_LABELS: dict[str, str] = {
    "TIER_50": "50 per day",
    "TIER_250": "250 per day",
    "TIER_1K": "1,000 per day",
    "TIER_10K": "10,000 per day",
    "TIER_100K": "1 lakh per day",
    "TIER_UNLIMITED": "Unlimited",
}

# Fallback when Meta returns a tier we don't recognise (new tier value
# Meta may introduce). We assume the most conservative known cap so
# the operator doesn't accidentally over-send. The UI label stays as
# the raw Meta value so it's debuggable.
_FALLBACK_TIER = "TIER_1K"

# Tier rarely changes (rolling 7-day evaluation on Meta's side), so an
# hourly cache is plenty fresh and keeps Graph-API calls negligible.
_TIER_CACHE_TTL = timedelta(hours=1)

# Meta's 24-hour rolling window — same unit Meta uses to compute the
# tier-limit denominator.
_USED_TODAY_WINDOW = timedelta(hours=24)


# --- Meta call -----------------------------------------------------------


async def _fetch_tier_from_meta(
    *,
    phone_id: str,
    access_token: str,
    api_version: str,
    http_client_factory: HttpClientFactory,
) -> str:
    """Hit `GET /{phone_id}?fields=messaging_limit_tier`. Returns the
    raw Meta value (e.g. `"TIER_10K"`). Raises `WhatsAppNotConnected`
    on any non-2xx so the router maps to 409 with the same operator-
    facing message every other Meta-rejected path uses."""
    url = (
        f"https://graph.facebook.com/{api_version}/{phone_id}"
        "?fields=messaging_limit_tier"
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    async with http_client_factory() as client:
        response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        raise WhatsAppNotConnected(
            f"Meta API rejected the capacity lookup: "
            f"{_extract_meta_error(response)}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise WhatsAppNotConnected(
            f"Unexpected Meta response shape: {body!r}"
        )
    tier = body.get("messaging_limit_tier")
    if not isinstance(tier, str) or not tier:
        # Meta sometimes returns no tier field for a never-active
        # number. Treat as the most conservative known tier.
        return _FALLBACK_TIER
    return tier


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


# --- Cache layer ---------------------------------------------------------


async def _get_tier_cached(
    session: AsyncSession,
    *,
    config: WhatsAppAccountConfig,
    access_token: str,
    http_client_factory: HttpClientFactory,
) -> str:
    """Return the cached `messaging_limit_tier` if it was refreshed
    within `_TIER_CACHE_TTL`; otherwise hit Meta and persist the new
    value before returning.

    First-fetch (both columns NULL) is treated as a cache miss. The
    update is committed inside this function so the next caller
    benefits — capacity lookups are read-heavy, so we'd rather pay one
    write per hour than dirty the session for the router to commit."""
    now = datetime.now(timezone.utc)
    cached_tier = config.messaging_limit_tier
    cached_at = config.tier_synced_at
    if (
        cached_tier
        and cached_at is not None
        and now - cached_at < _TIER_CACHE_TTL
    ):
        return cached_tier

    tier = await _fetch_tier_from_meta(
        phone_id=config.phone_id,
        access_token=access_token,
        api_version=config.api_version,
        http_client_factory=http_client_factory,
    )
    config.messaging_limit_tier = tier
    config.tier_synced_at = now
    await session.commit()
    await session.refresh(config)
    return tier


# --- Local count ---------------------------------------------------------


async def _count_unique_recipients_today(session: AsyncSession) -> int:
    """`COUNT(DISTINCT conversation_id)` of outbound WhatsApp messages
    sent in the last 24 hours. Matches Meta's "unique customers per
    24-hour rolling window" tier accounting — sending the same contact
    50 messages still counts as 1 toward the cap.

    RLS scopes both the `messages` and `conversations` rows to the
    active org automatically (both are TenantScoped), so this query
    does NOT need an explicit `org_id` filter."""
    cutoff = datetime.now(timezone.utc) - _USED_TODAY_WINDOW
    stmt = (
        select(func.count(func.distinct(Message.conversation_id)))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.channel == ConversationChannel.whatsapp,
            Message.direction == MessageDirection.out,
            Message.sent_at.is_not(None),
            Message.sent_at >= cutoff,
        )
    )
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    return int(value) if value else 0


# --- Public ---------------------------------------------------------------


async def get_send_capacity(
    session: AsyncSession,
    *,
    http_client_factory: HttpClientFactory = _default_http_client_factory,
) -> dict[str, Any]:
    """Snapshot of "can this org safely send a campaign right now?".

    Shape consumed by the campaign create modal's capacity banner:

        {
          "tier": "TIER_10K",
          "tier_label": "10,000 per day",
          "daily_limit": 10000,
          "used_today": 2847,
          "remaining": 7153,
          "usage_percent": 28,
          "is_unlimited": False,
        }

    `remaining` is `-1` and `usage_percent` is `0` when `is_unlimited`
    — the UI uses those sentinels to hide the progress bar and the
    "X remaining" copy.

    Raises `WhatsAppNotConnected` if the active org has no connected
    integration. The router maps that to HTTP 409, same as every other
    capacity-dependent endpoint.
    """
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
    plaintext_token = decrypt(integration.access_token_enc)

    tier = await _get_tier_cached(
        session,
        config=config,
        access_token=plaintext_token,
        http_client_factory=http_client_factory,
    )
    tier_label = TIER_LABELS.get(tier, tier)
    daily_limit = TIER_LIMITS.get(tier, TIER_LIMITS[_FALLBACK_TIER])
    used = await _count_unique_recipients_today(session)

    is_unlimited = daily_limit == -1
    if is_unlimited:
        remaining = -1
        usage_percent = 0
    else:
        remaining = max(0, daily_limit - used)
        usage_percent = (
            round(used / daily_limit * 100) if daily_limit else 0
        )
        # Cap display percent at 100 — possible if a sudden burst
        # raced the tier-refresh cron (won't exist here yet, but the
        # invariant is cheap to keep).
        usage_percent = min(usage_percent, 100)

    return {
        "tier": tier,
        "tier_label": tier_label,
        "daily_limit": daily_limit,
        "used_today": used,
        "remaining": remaining,
        "usage_percent": usage_percent,
        "is_unlimited": is_unlimited,
    }


__all__ = [
    "TIER_LABELS",
    "TIER_LIMITS",
    "get_send_capacity",
]
