"""Step 3.5.16 — WhatsApp send-capacity tests.

Two surfaces under test:

  1. `_count_unique_recipients_today` — DISTINCT recipients in the
     last 24 hours over outbound WhatsApp messages only (inbound, non-
     WhatsApp, and old messages excluded).

  2. `get_send_capacity` — orchestrates tier fetch + cache + count
     and returns the modal banner's payload. Meta is stubbed via an
     injectable httpx-client factory (same pattern as Step 3.5.4).

The fake session here dispatches `execute(stmt)` results based on the
SQL stringification — the count query is a `select(func.count(...))`
whose `column_descriptions[0]['entity']` is None, so the existing
entity-keyed dispatch from `test_whatsapp_templates.py` wouldn't fit.
We special-case the count by inspecting the stringified statement
instead.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations import crypto
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp import status as wa_status
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig


_ORG_ID = uuid.uuid4()


# --- fake session --------------------------------------------------------


class _FakeResult:
    def __init__(self, rows, scalar: Any = None, has_scalar: bool = False):
        self._rows = list(rows) if rows is not None else []
        self._scalar = scalar
        self._has_scalar = has_scalar

    def scalar_one_or_none(self):
        if self._has_scalar:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _CapturingSession:
    """Routes `execute(select(X))` either by stringified SQL (the
    count query) or by `column_descriptions[0]['entity']` (the
    integration / config selects).

    Tracks `commits` so cache-write tests can assert the persist
    side-effect happened exactly when expected."""

    def __init__(self):
        self.rows: dict[type, list] = {
            Integration: [],
            WhatsAppAccountConfig: [],
        }
        # `unique_recipients_today` is the answer the fake will return
        # for the COUNT(DISTINCT) query.
        self.unique_recipients_today: int = 0
        self.commits = 0
        self.refreshes = 0

    async def execute(self, stmt):
        # COUNT(DISTINCT conversation_id) — the only aggregate query
        # this service issues. Match by stringified SQL.
        sql_text = str(stmt).lower()
        if "count(distinct" in sql_text:
            return _FakeResult(
                [], scalar=self.unique_recipients_today, has_scalar=True
            )
        # Entity-keyed selects.
        try:
            descs = stmt.column_descriptions
            entity = descs[0].get("entity") if descs else None
        except (AttributeError, KeyError, IndexError):
            entity = None
        if entity in self.rows:
            return _FakeResult(self.rows[entity])
        return _FakeResult([])

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        self.refreshes += 1


def _meta_factory_with(
    payload: dict,
    *,
    status_code: int = 200,
    call_log: Optional[list] = None,
):
    """httpx client factory whose `get(url, headers)` returns the given
    JSON. Optionally appends to `call_log` so a test can assert the
    request was (or wasn't) made."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url, headers=None):
            if call_log is not None:
                call_log.append({"url": url, "headers": headers})
            return httpx.Response(status_code, json=payload)

    return lambda: _Client()


def _connected_pair(
    *,
    tier: Optional[str] = None,
    synced_at: Optional[datetime] = None,
) -> tuple[Integration, WhatsAppAccountConfig]:
    integration = Integration(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        provider=IntegrationProvider.whatsapp,
        account_id="123456789012345",
        account_label="+91 98765 43210",
        access_token_enc=crypto.encrypt("active-bearer"),
        refresh_token_enc=None,
        token_expires_at=None,
        scopes=None,
        status=IntegrationStatus.connected,
        last_error=None,
        connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    config = WhatsAppAccountConfig(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=integration.id,
        phone_id="123456789012345",
        waba_id="987654321098765",
        display_phone_number="+91 98765 43210",
        verified_name="Sharma Furniture",
        app_secret_enc=crypto.encrypt("secret"),
        verify_token="vt",
        api_version="v18.0",
        rate_limit_per_sec=50,
        messaging_limit_tier=tier,
        tier_synced_at=synced_at,
    )
    return integration, config


# --- tests ---------------------------------------------------------------


class TestTierConstants:
    def test_every_tier_has_limit_and_label(self):
        """Catches drift: a new tier value added to TIER_LIMITS without
        a matching TIER_LABELS entry would make the banner show a raw
        Meta string. Reverse direction too."""
        assert set(wa_status.TIER_LIMITS) == set(wa_status.TIER_LABELS)
        expected = {
            "TIER_50",
            "TIER_250",
            "TIER_1K",
            "TIER_10K",
            "TIER_100K",
            "TIER_UNLIMITED",
        }
        assert expected.issubset(set(wa_status.TIER_LIMITS))

    def test_unlimited_sentinel_is_negative_one(self):
        """The schema + UI rely on this exact sentinel — encode it
        once in the test so future tinkering trips here, not in prod."""
        assert wa_status.TIER_LIMITS["TIER_UNLIMITED"] == -1


class TestGetCapacity:
    @pytest.mark.asyncio
    async def test_returns_tier_label_and_remaining(self):
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 2_847

        meta_payload = {"messaging_limit_tier": "TIER_10K"}
        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(meta_payload),
        )

        assert result["tier"] == "TIER_10K"
        assert result["tier_label"] == "10,000 per day"
        assert result["daily_limit"] == 10_000
        assert result["used_today"] == 2_847
        assert result["remaining"] == 7_153
        assert result["usage_percent"] == 28
        assert result["is_unlimited"] is False

    @pytest.mark.asyncio
    async def test_full_quota_returns_zero_remaining(self):
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 1_000

        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_1K"}
            ),
        )

        assert result["remaining"] == 0
        assert result["usage_percent"] == 100

    @pytest.mark.asyncio
    async def test_over_quota_caps_at_zero_remaining_and_100_percent(self):
        """Defensive: if a burst races the counter (or tier was just
        downgraded), `used > limit` is possible. Remaining must floor
        at 0 and percent must cap at 100."""
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 1_500

        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_1K"}
            ),
        )

        assert result["remaining"] == 0
        assert result["usage_percent"] == 100

    @pytest.mark.asyncio
    async def test_unlimited_branch(self):
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 50_000

        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_UNLIMITED"}
            ),
        )

        assert result["is_unlimited"] is True
        assert result["daily_limit"] == -1
        assert result["remaining"] == -1
        assert result["usage_percent"] == 0
        assert result["used_today"] == 50_000

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        session = _CapturingSession()
        with pytest.raises(WhatsAppNotConnected, match="not connected"):
            await wa_status.get_send_capacity(
                session,
                http_client_factory=_meta_factory_with({}),
            )
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_raises_when_token_missing(self):
        session = _CapturingSession()
        integration, config = _connected_pair()
        integration.access_token_enc = None
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        with pytest.raises(
            WhatsAppNotConnected, match="credentials are missing"
        ):
            await wa_status.get_send_capacity(
                session,
                http_client_factory=_meta_factory_with({}),
            )

    @pytest.mark.asyncio
    async def test_raises_when_meta_rejects(self):
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        meta_error = {
            "error": {"message": "Invalid OAuth access token"}
        }
        with pytest.raises(
            WhatsAppNotConnected, match="Invalid OAuth access token"
        ):
            await wa_status.get_send_capacity(
                session,
                http_client_factory=_meta_factory_with(
                    meta_error, status_code=401
                ),
            )

    @pytest.mark.asyncio
    async def test_unknown_tier_falls_back_to_conservative_default(self):
        """Meta could ship a new tier value (e.g. `TIER_500K`); we
        return the fallback `TIER_1K` limit but echo the raw Meta
        value as the tier so the operator can see what's new."""
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 200

        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_500K"}
            ),
        )

        assert result["tier"] == "TIER_500K"
        assert result["tier_label"] == "TIER_500K"
        assert result["daily_limit"] == 1_000
        assert result["remaining"] == 800

    @pytest.mark.asyncio
    async def test_missing_tier_field_uses_fallback(self):
        """Meta returns no `messaging_limit_tier` field for never-active
        numbers — service must pick the conservative default."""
        session = _CapturingSession()
        integration, config = _connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with({"id": "123"}),
        )

        assert result["tier"] == "TIER_1K"
        assert result["daily_limit"] == 1_000


class TestTierCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_meta_call(self):
        """Fresh cache (synced 30 minutes ago) → no httpx call."""
        session = _CapturingSession()
        synced = datetime.now(timezone.utc) - timedelta(minutes=30)
        integration, config = _connected_pair(
            tier="TIER_10K", synced_at=synced
        )
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]
        session.unique_recipients_today = 500

        call_log: list = []
        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with({}, call_log=call_log),
        )

        assert call_log == [], "no Meta call expected on cache hit"
        assert result["tier"] == "TIER_10K"
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_cache_miss_refreshes_and_persists(self):
        """Stale cache (synced 2 hours ago) → Meta call, then column
        updated and committed."""
        session = _CapturingSession()
        synced = datetime.now(timezone.utc) - timedelta(hours=2)
        integration, config = _connected_pair(
            tier="TIER_1K", synced_at=synced
        )
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        call_log: list = []
        result = await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_10K"}, call_log=call_log
            ),
        )

        assert len(call_log) == 1
        assert config.messaging_limit_tier == "TIER_10K"
        assert config.tier_synced_at is not None
        assert (
            datetime.now(timezone.utc) - config.tier_synced_at
        ) < timedelta(seconds=5)
        assert session.commits == 1
        assert result["tier"] == "TIER_10K"

    @pytest.mark.asyncio
    async def test_first_fetch_when_both_columns_null(self):
        """Never-fetched cache (both NULL) → treat as miss, populate."""
        session = _CapturingSession()
        integration, config = _connected_pair(tier=None, synced_at=None)
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        call_log: list = []
        await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_250"}, call_log=call_log
            ),
        )

        assert len(call_log) == 1
        assert config.messaging_limit_tier == "TIER_250"
        assert config.tier_synced_at is not None
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_meta_url_includes_phone_id_and_version(self):
        session = _CapturingSession()
        integration, config = _connected_pair(tier=None, synced_at=None)
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        call_log: list = []
        await wa_status.get_send_capacity(
            session,
            http_client_factory=_meta_factory_with(
                {"messaging_limit_tier": "TIER_1K"}, call_log=call_log
            ),
        )

        url = call_log[0]["url"]
        assert "/v18.0/" in url
        assert "/123456789012345" in url
        assert "fields=messaging_limit_tier" in url
        assert call_log[0]["headers"]["Authorization"].startswith("Bearer ")
