"""Meta Ads ad-id → campaign-name resolver
(whatsapp-platform-upgrade Step 24).

Meta's inbound ``referral`` block carries an ``source_id`` (the ad
creative id) but not the friendly campaign name an operator wants
to see in the attribution chip. This module is the single
choke-point that resolves ``ad_id → {ad_name, campaign_name,
campaign_id, ad_account_id}`` using the Meta Graph API.

Design notes
------------

* **Best-effort.** When the org doesn't have a connected
  ``meta_ads`` integration, or Meta returns 4xx for the ad id, we
  return ``None``. The conversation still carries the raw
  ``source_id`` on its referral payload column, so the chip
  degrades to "Meta Ad #<id>" instead of a friendly name.

* **Per-process LRU cache.** Campaign names change rarely. We
  cache the resolved dict for 24 hours keyed on ``(org_id,
  ad_id)`` so 100 inbound messages from the same ad cost one
  Graph call. The cache is process-local — sufficient for one
  worker; future Redis lift moves to ``shared/cache.py`` when one
  exists. A miss-cache hit (we asked Meta and got nothing) is
  also cached for 1 hour so a deleted ad doesn't generate one
  Graph call per inbound forever.

* **Never raises into the webhook handler.** Anything unexpected
  (token expired, Meta 5xx, network) returns ``None`` and logs
  the exception. Inbound message processing must never be
  derailed by an attribution lookup.

Returned shape::

    {
      "ad_id": "23845...",
      "ad_name": "Summer Sale CTWA",
      "campaign_id": "23845...",
      "campaign_name": "Summer Sale",
      "ad_account_id": "act_123...",
    }
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.meta.api_client import (
    MetaGraphClient,
    MetaTokenExpiredError,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)

logger = logging.getLogger(__name__)


_HIT_TTL = 60 * 60 * 24  # 24 hours
_MISS_TTL = 60 * 60  # 1 hour — let Meta heal


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    """Cached lookup result. ``value=None`` is the negative-cache
    sentinel (we asked Meta, the ad doesn't exist / is unreachable).
    ``expires_at`` is a unix timestamp; the cache reads it on each
    access without needing a background sweeper."""

    value: dict | None
    expires_at: float


# Process-local — keyed on `(org_id, ad_id)`. Bounded by
# `_MAX_ENTRIES` so a long-running worker doesn't slowly bloat.
_MAX_ENTRIES = 2_000
_cache: dict[tuple[str, str], _CacheEntry] = {}


def _cache_get(key: tuple[str, str]) -> _CacheEntry | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    if entry.expires_at < time.time():
        _cache.pop(key, None)
        return None
    return entry


def _cache_put(key: tuple[str, str], value: dict | None, ttl: int) -> None:
    if len(_cache) >= _MAX_ENTRIES:
        # Cheap eviction — drop one arbitrary entry. The LRU policy
        # isn't worth the bookkeeping for a 2K-entry cache.
        _cache.pop(next(iter(_cache)), None)
    _cache[key] = _CacheEntry(value=value, expires_at=time.time() + ttl)


def reset_cache() -> None:
    """Test helper — wipes the in-process cache. Production callers
    should never need this; the TTL handles staleness."""
    _cache.clear()


async def _resolve_meta_ads_integration(
    session: AsyncSession, *, org_id: uuid.UUID
) -> Integration | None:
    row = (
        await session.execute(
            select(Integration).where(
                Integration.org_id == org_id,
                Integration.provider == IntegrationProvider.meta_ads,
                Integration.status == IntegrationStatus.connected,
            )
        )
    ).scalar_one_or_none()
    return row


async def resolve_ad(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    ad_id: str,
) -> dict | None:
    """Resolve a Meta ad id to its campaign + ad metadata.

    Returns the metadata dict on success, ``None`` when the org has
    no connected Meta Ads integration / Meta refused the lookup /
    the ad was deleted. Safe to call inside webhook handlers — never
    raises.

    The function caches both positive and negative results so a
    high-volume ad doesn't re-hit the Graph API. Operators who fix
    a misconfigured integration can call :func:`reset_cache` (or
    just wait out the TTL) to retry.
    """
    if not ad_id:
        return None
    key = (str(org_id), str(ad_id))
    cached = _cache_get(key)
    if cached is not None:
        return cached.value

    integration = await _resolve_meta_ads_integration(session, org_id=org_id)
    if integration is None:
        # No integration — no friendly name. Cache the negative so
        # subsequent ad referrals don't keep retrying the lookup.
        _cache_put(key, None, _MISS_TTL)
        return None

    try:
        client = MetaGraphClient(integration=integration, session=session)
        # Graph API: `/<ad_id>?fields=name,campaign{name,id},
        # account_id` is the smallest payload that gets us the
        # operator-facing labels + the deeplink path.
        result = await client.get(
            f"/{ad_id}",
            params={"fields": "name,campaign{name,id},account_id"},
        )
    except MetaTokenExpiredError:
        logger.info(
            "meta ads token expired during ad %s lookup (org=%s)",
            ad_id,
            org_id,
        )
        _cache_put(key, None, _MISS_TTL)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("meta ads lookup failed for ad=%s org=%s", ad_id, org_id)
        _cache_put(key, None, _MISS_TTL)
        return None

    if not isinstance(result, dict) or not result.get("name"):
        _cache_put(key, None, _MISS_TTL)
        return None

    campaign = result.get("campaign") if isinstance(result.get("campaign"), dict) else {}
    metadata = {
        "ad_id": str(ad_id),
        "ad_name": str(result.get("name") or "") or None,
        "campaign_id": (
            str(campaign.get("id") or "") or None if isinstance(campaign, dict) else None
        ),
        "campaign_name": (
            str(campaign.get("name") or "") or None if isinstance(campaign, dict) else None
        ),
        "ad_account_id": str(result.get("account_id") or "") or None,
    }
    _cache_put(key, metadata, _HIT_TTL)
    return metadata


def deeplink_for_ad(metadata: dict) -> str | None:
    """Build the Meta Ads Manager deeplink for the resolved ad.

    Format mirrors Meta's documented deeplink so an operator
    clicking the attribution chip lands on the ad's row in their
    own Ads Manager. Returns ``None`` when ``ad_account_id`` is
    missing (Meta requires it in the URL)."""
    if not isinstance(metadata, dict):
        return None
    account = metadata.get("ad_account_id")
    ad_id = metadata.get("ad_id")
    if not account or not ad_id:
        return None
    # Meta Ads Manager URL — `?act=<account>&selected_ad_ids=<id>`.
    return f"https://www.facebook.com/adsmanager/manage/ads?act={account}&selected_ad_ids={ad_id}"


__all__ = [
    "deeplink_for_ad",
    "resolve_ad",
    "reset_cache",
]
