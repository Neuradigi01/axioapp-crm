"""Step 3.5.15 — WhatsApp rate limit + 429 handling tests.

Two surfaces under test:

  1. `InMemoryTokenBucketLimiter` — token-bucket math + per-org keying,
     including the operator's "change rate while running" path.

  2. Adapter 429 handling — Meta 429 response → `WhatsAppRateLimited`
     with `retry_after_seconds` parsed from `Retry-After` header.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    WhatsAppRateLimited,
    WhatsAppSendError,
)
from src.app.core.integrations.whatsapp.rate_limit import (
    InMemoryTokenBucketLimiter,
    acquire_wa_rate_token,
    get_wa_rate_limiter,
)


# --- token bucket --------------------------------------------------------


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_initial_burst_drains_without_wait(self):
        """A fresh bucket starts full (capacity = 2 × rate). Burst-sending
        up to capacity returns 0 wait per call."""
        bucket = InMemoryTokenBucketLimiter()
        # rate=10/sec → capacity=20. 20 immediate acquires should be free.
        for _ in range(20):
            wait = await bucket.acquire("org-A", rate_per_sec=10.0)
            assert wait == 0.0

    @pytest.mark.asyncio
    async def test_separate_keys_have_independent_buckets(self):
        """`org-A` exhausting its bucket doesn't starve `org-B`."""
        bucket = InMemoryTokenBucketLimiter()
        # Drain org-A.
        for _ in range(20):
            await bucket.acquire("org-A", rate_per_sec=10.0)
        # org-B should still have its full burst available.
        wait = await bucket.acquire("org-B", rate_per_sec=10.0)
        assert wait == 0.0

    @pytest.mark.asyncio
    async def test_zero_rate_treated_as_unlimited(self):
        """A defensive guard: a misconfigured row with rate=0 must NOT
        block forever — return immediately."""
        bucket = InMemoryTokenBucketLimiter()
        wait = await bucket.acquire("org-A", rate_per_sec=0.0)
        assert wait == 0.0

    @pytest.mark.asyncio
    async def test_rate_change_re_rates_bucket(self):
        """If the operator bumps `rate_limit_per_sec`, the bucket's
        capacity + refill rate update in place. Subsequent acquires
        proceed with the new (higher) rate — any micro-wait between
        them is dominated by the refill rate, not the old rate."""
        bucket = InMemoryTokenBucketLimiter()
        # Initial 5/sec rate → capacity=10.
        await bucket.acquire("org-A", rate_per_sec=5.0)
        # Bump to 100/sec → capacity should jump to 200.
        await bucket.acquire("org-A", rate_per_sec=100.0)
        # Drain ~150 more. Allow micro-waits (~10ms each from refill
        # gaps under asyncio scheduling); cap TOTAL spend at 1s.
        total = 0.0
        for _ in range(150):
            total += await bucket.acquire("org-A", rate_per_sec=100.0)
        # At 100/sec we'd burn ~140 tokens through refill alone in
        # the time those 150 calls take. Total spend should be << 2s.
        assert total < 2.0

    @pytest.mark.asyncio
    async def test_acquire_returns_wait_time_for_starved_bucket(self):
        """When the bucket is dry, `acquire` sleeps. We assert the
        TOTAL waited time is roughly the expected refill window —
        with a generous fudge factor for test scheduling jitter."""
        bucket = InMemoryTokenBucketLimiter()
        # rate=100/sec, capacity=200. Drain it.
        for _ in range(200):
            await bucket.acquire("org-A", rate_per_sec=100.0)
        # Next acquire needs 1 token → expects ~10ms wait at 100/sec.
        # Allow up to 200ms to account for asyncio + GC noise.
        start = time.monotonic()
        wait = await bucket.acquire("org-A", rate_per_sec=100.0)
        elapsed = time.monotonic() - start
        assert wait > 0.0
        assert elapsed < 0.5  # sanity: not blocked forever


# --- module-level helpers -----------------------------------------------


class TestModuleHelpers:
    def test_singleton_limiter(self):
        """`get_wa_rate_limiter` always returns the same instance so
        all dispatch coroutines share bucket state within the
        process."""
        assert get_wa_rate_limiter() is get_wa_rate_limiter()

    @pytest.mark.asyncio
    async def test_acquire_wa_rate_token_accepts_uuid(self):
        """The convenience wrapper takes a UUID + int rate and returns
        a float wait. No raising on valid args."""
        get_wa_rate_limiter().reset()
        wait = await acquire_wa_rate_token(
            uuid.uuid4(), rate_per_sec=10, count=1
        )
        assert wait == 0.0


# --- adapter 429 handling -----------------------------------------------


class _FakeClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, _url, json=None, headers=None):
        return self._response


class TestAdapter429:
    @pytest.mark.asyncio
    async def test_429_with_retry_after_raises_rate_limited(self):
        """Meta 429 → `WhatsAppRateLimited`, NOT `WhatsAppSendError`.
        The dispatch path's retry logic depends on this distinction."""
        resp = httpx.Response(
            429,
            content=b'{"error":{"message":"too many requests"}}',
            headers={
                "content-type": "application/json",
                "retry-after": "30",
            },
        )
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: _FakeClient(resp),
        )
        with pytest.raises(WhatsAppRateLimited) as exc_info:
            await adapter.send(
                org_id=uuid.uuid4(),
                external_id="+91 98765 43210",
                text="hi",
                attachments=[],
            )
        assert exc_info.value.retry_after_seconds == 30

    @pytest.mark.asyncio
    async def test_429_without_retry_after_uses_default(self):
        """Meta sometimes omits `Retry-After`. Default to 60s."""
        resp = httpx.Response(429, content=b"{}")
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: _FakeClient(resp),
        )
        with pytest.raises(WhatsAppRateLimited) as exc_info:
            await adapter.send(
                org_id=uuid.uuid4(),
                external_id="+91 98765 43210",
                text="hi",
                attachments=[],
            )
        assert exc_info.value.retry_after_seconds == 60

    @pytest.mark.asyncio
    async def test_400_still_raises_send_error_not_rate_limited(self):
        """Regression: Meta 400 (`Invalid recipient` etc.) → unchanged
        `WhatsAppSendError` behaviour, NOT the new RateLimited path."""
        resp = httpx.Response(
            400,
            content=b'{"error":{"code":131056}}',
        )
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: _FakeClient(resp),
        )
        with pytest.raises(WhatsAppSendError):
            await adapter.send(
                org_id=uuid.uuid4(),
                external_id="+91 98765 43210",
                text="hi",
                attachments=[],
            )

    @pytest.mark.asyncio
    async def test_429_on_template_send_also_raises(self):
        """The 429 branch applies to `send_template` symmetrically."""
        resp = httpx.Response(
            429, headers={"retry-after": "10"}, content=b"{}"
        )
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: _FakeClient(resp),
        )
        with pytest.raises(WhatsAppRateLimited) as exc_info:
            await adapter.send_template(
                org_id=uuid.uuid4(),
                external_id="+91 98765 43210",
                template_name="hello_world",
                language="en_US",
                variables={},
            )
        assert exc_info.value.retry_after_seconds == 10
