"""Fail-closed behaviour of the AI-assistants public rate limiter
(``tasks/ai-assistants`` Step 14).

Verifies that when the shared Redis client returns ``None`` (dev
shell without Redis) or raises a ``RedisError`` mid-flight, the
:func:`check_ai_public_rate_limits` returns ``allowed=False`` with
``reason='redis_unavailable'`` and a 30s ``Retry-After``.

Deliberately DOES NOT fall through to the in-process bucket — chat
requests spend real OpenAI money and the failure mode we want under
Redis outage is "widget shows retry later", not "spend 10× the daily
budget because the limiter is silently open".
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.embed.rate_limit import (
    AiPublicRateLimitResult,
    check_ai_public_rate_limits,
)


@pytest.mark.asyncio
async def test_fail_closed_when_redis_client_none(monkeypatch) -> None:
    """When ``rate_limit_shared._redis()`` returns None (no Redis in
    dev), the AI public limiter refuses rather than falling through."""
    from src.app.shared import rate_limit_shared

    monkeypatch.setattr(rate_limit_shared, "_redis", lambda: None)

    result = await check_ai_public_rate_limits(
        ip="203.0.113.1",
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        per_key_limit=300,
    )
    assert isinstance(result, AiPublicRateLimitResult)
    assert result.allowed is False
    assert result.reason == "redis_unavailable"
    assert result.retry_after_seconds == 30


@pytest.mark.asyncio
async def test_fail_closed_when_redis_pipeline_raises(monkeypatch) -> None:
    """RedisError during the sliding-window transaction still
    fails-closed — no fall-through to the in-process bucket."""
    from redis.exceptions import RedisError

    from src.app.shared import rate_limit_shared

    class _FakePipe:
        def zremrangebyscore(self, *a, **kw):
            return self

        def zcard(self, *a, **kw):
            return self

        def zadd(self, *a, **kw):
            return self

        def expire(self, *a, **kw):
            return self

        async def execute(self):
            raise RedisError("simulated outage")

    class _FakeClient:
        def pipeline(self, transaction: bool = True):
            return _FakePipe()

    monkeypatch.setattr(rate_limit_shared, "_redis", lambda: _FakeClient())

    result = await check_ai_public_rate_limits(
        ip="203.0.113.2",
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        per_key_limit=300,
    )
    assert result.allowed is False
    assert result.reason == "redis_unavailable"
    assert result.retry_after_seconds == 30


@pytest.mark.asyncio
async def test_admits_first_hit_under_limit(monkeypatch) -> None:
    """Happy path: fake pipeline returns count=0 (no prior hits) so
    the caller is admitted."""
    from src.app.shared import rate_limit_shared

    class _FakePipe:
        def zremrangebyscore(self, *a, **kw):
            return self

        def zcard(self, *a, **kw):
            return self

        def zadd(self, *a, **kw):
            return self

        def expire(self, *a, **kw):
            return self

        async def execute(self):
            # Match the pipeline shape: (remove_count, count_before,
            # add_result, expire_result).
            return (0, 0, 1, True)

    class _FakeClient:
        def pipeline(self, transaction: bool = True):
            return _FakePipe()

    monkeypatch.setattr(rate_limit_shared, "_redis", lambda: _FakeClient())

    result = await check_ai_public_rate_limits(
        ip="203.0.113.3",
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        per_key_limit=300,
    )
    assert result.allowed is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_rejects_when_per_key_bucket_full(monkeypatch) -> None:
    """When ``count_before >= limit`` the caller is rejected with the
    matching bucket name."""
    from src.app.shared import rate_limit_shared

    # Return count depending on which key was queried — per-IP is
    # checked first, then per-key, then per-org. We want per-IP under
    # limit + per-key over.
    call_count = {"n": 0}

    class _FakePipe:
        def zremrangebyscore(self, *a, **kw):
            return self

        def zcard(self, *a, **kw):
            return self

        def zadd(self, *a, **kw):
            return self

        def expire(self, *a, **kw):
            return self

        async def execute(self):
            call_count["n"] += 1
            # First call (per-IP) admits; second call (per-key) is over.
            count_before = 0 if call_count["n"] == 1 else 500
            return (0, count_before, 1, True)

    class _FakeClient:
        def pipeline(self, transaction: bool = True):
            return _FakePipe()

    monkeypatch.setattr(rate_limit_shared, "_redis", lambda: _FakeClient())

    result = await check_ai_public_rate_limits(
        ip="203.0.113.4",
        key_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        per_key_limit=300,
    )
    assert result.allowed is False
    assert result.reason == "per_key"
    assert result.retry_after_seconds == 60
