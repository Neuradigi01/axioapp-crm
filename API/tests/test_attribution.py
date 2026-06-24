"""whatsapp-platform-upgrade Step 24 — click-to-WhatsApp attribution
boundary tests.

Pure-Python coverage of:
  * Meta referral parser inside ``WhatsAppAdapter.parse_webhook``.
  * ``ads_lookup.deeplink_for_ad`` URL construction.
  * ``ads_lookup`` in-process cache (positive + negative hits +
    TTL expiry).

The Graph-API call inside :func:`resolve_ad` is exercised by the
smoke flow against a sandbox account — same precedent as prior
steps.

Cases:
  1. Parser populates ``referral`` when ``messages[0].referral`` is
     present.
  2. Parser leaves ``referral=None`` on a plain inbound (no ad).
  3. Parser preserves all referral keys (forensics).
  4. Parser tolerates a non-dict referral block gracefully.
  5. ``deeplink_for_ad`` builds the Meta Ads Manager URL.
  6. ``deeplink_for_ad`` returns None when ``ad_account_id`` is
     missing.
  7. ``deeplink_for_ad`` returns None on non-dict input.
  8. Cache hit returns the same payload without re-calling.
  9. Cache miss + put + read round-trip works.
 10. Negative-cache entry prevents repeated misses.
 11. Cache eviction kicks in past ``_MAX_ENTRIES``.
"""
from __future__ import annotations

import time

import pytest

from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter
from src.app.core.integrations.meta import ads_lookup


def _make_adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id="phone-x",
        token="token-x",
        app_secret="secret-x",
        verify_token="verify-x",
        api_version="v19.0",
    )


def _wrap_message(message: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {"value": {"messages": [message]}}
                ]
            }
        ]
    }


class TestReferralParser:
    def test_populates_referral_field(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "text": {"body": "Hi from ad"},
            "referral": {
                "source_url": "https://fb.me/ad/abc",
                "source_id": "23845001",
                "source_type": "ad",
                "headline": "Summer Sale",
                "body": "Get 30% off",
                "ctwa_clid": "clid-1",
            },
        }
        parsed = _make_adapter().parse_webhook(_wrap_message(msg))
        assert parsed.referral is not None
        assert parsed.referral["source_id"] == "23845001"
        assert parsed.referral["source_type"] == "ad"
        assert parsed.referral["headline"] == "Summer Sale"
        assert parsed.referral["ctwa_clid"] == "clid-1"

    def test_organic_inbound_has_no_referral(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.Y",
            "timestamp": "1700000000",
            "text": {"body": "Hello"},
        }
        parsed = _make_adapter().parse_webhook(_wrap_message(msg))
        assert parsed.referral is None

    def test_referral_keys_preserved(self):
        # Future Meta-side fields should pass through verbatim so
        # we don't lose forensics on schema drift.
        msg = {
            "from": "919999988888",
            "id": "wamid.Z",
            "timestamp": "1700000000",
            "text": {"body": "Hi"},
            "referral": {
                "source_url": "https://fb.me/ad/x",
                "source_id": "ad-1",
                "source_type": "ad",
                "future_meta_field": "value-from-the-future",
            },
        }
        parsed = _make_adapter().parse_webhook(_wrap_message(msg))
        assert parsed.referral["future_meta_field"] == "value-from-the-future"

    def test_non_dict_referral_ignored(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.A",
            "timestamp": "1700000000",
            "text": {"body": "Hi"},
            "referral": "not-a-dict",
        }
        parsed = _make_adapter().parse_webhook(_wrap_message(msg))
        assert parsed.referral is None

    def test_empty_dict_referral_treated_as_none(self):
        # Meta sometimes ships an empty `{}` rather than omitting
        # the key — treat as no attribution.
        msg = {
            "from": "919999988888",
            "id": "wamid.B",
            "timestamp": "1700000000",
            "text": {"body": "Hi"},
            "referral": {},
        }
        parsed = _make_adapter().parse_webhook(_wrap_message(msg))
        assert parsed.referral is None


class TestDeeplink:
    def test_builds_ads_manager_url(self):
        url = ads_lookup.deeplink_for_ad(
            {
                "ad_id": "23845001",
                "ad_account_id": "act_12345",
            }
        )
        assert url is not None
        assert "act=act_12345" in url
        assert "selected_ad_ids=23845001" in url
        assert url.startswith("https://www.facebook.com/adsmanager")

    def test_returns_none_without_account(self):
        assert (
            ads_lookup.deeplink_for_ad({"ad_id": "23845001"}) is None
        )

    def test_returns_none_on_non_dict(self):
        assert ads_lookup.deeplink_for_ad(None) is None  # type: ignore[arg-type]
        assert ads_lookup.deeplink_for_ad("garbage") is None  # type: ignore[arg-type]


class TestCache:
    def setup_method(self) -> None:
        ads_lookup.reset_cache()

    def teardown_method(self) -> None:
        ads_lookup.reset_cache()

    def test_positive_cache_round_trip(self):
        key = ("org-1", "ad-1")
        value = {"ad_id": "ad-1", "campaign_name": "Hot Sale"}
        ads_lookup._cache_put(key, value, ttl=60)
        entry = ads_lookup._cache_get(key)
        assert entry is not None
        assert entry.value == value

    def test_negative_cache_round_trip(self):
        key = ("org-1", "ad-deleted")
        ads_lookup._cache_put(key, None, ttl=60)
        entry = ads_lookup._cache_get(key)
        assert entry is not None
        assert entry.value is None

    def test_ttl_expiry(self, monkeypatch):
        key = ("org-1", "ad-1")
        ads_lookup._cache_put(key, {"ad_id": "ad-1"}, ttl=60)
        # Move clock past TTL.
        original_time = time.time
        monkeypatch.setattr(
            ads_lookup.time, "time", lambda: original_time() + 120
        )
        assert ads_lookup._cache_get(key) is None

    def test_eviction_past_max_entries(self, monkeypatch):
        monkeypatch.setattr(ads_lookup, "_MAX_ENTRIES", 3)
        ads_lookup.reset_cache()
        for i in range(5):
            ads_lookup._cache_put(
                ("org-1", f"ad-{i}"), {"ad_id": f"ad-{i}"}, ttl=60
            )
        # We can only assert the cache stayed bounded; the exact
        # eviction policy is a "drop one arbitrary entry" — not
        # LRU — so we don't pin which keys remain.
        assert len(ads_lookup._cache) <= 3
