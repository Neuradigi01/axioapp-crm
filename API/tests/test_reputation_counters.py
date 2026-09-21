"""Coverage for the Redis time-bucketed counters (Step 2 of
tasks/email-reputation-warmup/).

Uses a fake Redis client injected via monkeypatch — no live Redis
required. The fake mirrors the aioredis API surface the counters
module uses (``pipeline``, ``mget``, ``scan_iter``, ``delete``,
``incrby``, ``expire``).

Redis' TTL is not simulated; we test:

  * key format (``rep:{org}:{envelope}:{domain}:{event}:{bucket}``)
  * TTL set to 25h on every INCR
  * 24-bucket read is one MGET pipelined round-trip
  * out-of-window bucket keys never enter the sum
  * concurrent incr semantics (pipeline's INCRBY is atomic)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from redis.exceptions import RedisError

from src.app.core.email.reputation import counters

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake Redis client — mirrors the tiny surface counters.py actually uses.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-memory Redis stand-in.

    Tracks:
      * ``store`` — key → int value
      * ``ttls`` — key → seconds set by EXPIRE (last-write-wins)
      * ``calls.pipeline_execs`` — number of pipeline.execute() calls
      * ``calls.mget_batches`` — one entry per MGET call, holding the
        keys requested (lets tests assert 24 buckets went in one call).
    """

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.calls: dict[str, Any] = {"pipeline_execs": 0, "mget_batches": []}
        self.raise_on_mget = False
        self.raise_on_pipeline_execute = False

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def mget(self, keys: list[str]) -> list[str | None]:
        if self.raise_on_mget:
            raise RedisError("simulated read outage")
        self.calls["mget_batches"].append(list(keys))
        return [str(self.store[k]) if k in self.store else None for k in keys]

    async def delete(self, key: str) -> int:
        removed = 1 if key in self.store else 0
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return removed

    async def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        # Yield every key that matches the prefix (naïve — the real
        # scan_iter is a coroutine iterator; we mimic the shape).
        prefix = match.rstrip("*")
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key


class _FakePipeline:
    """Pipeline that queues INCRBY + EXPIRE commands and applies them
    on ``execute``. Matches the shape ``counters.incr_counter`` calls."""

    def __init__(self, client: _FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def incrby(self, key: str, amount: int) -> _FakePipeline:
        self._ops.append(("incrby", (key, amount)))
        return self

    def expire(self, key: str, ttl: int) -> _FakePipeline:
        self._ops.append(("expire", (key, ttl)))
        return self

    async def execute(self) -> list[Any]:
        if self._client.raise_on_pipeline_execute:
            raise RedisError("simulated pipeline outage")
        self._client.calls["pipeline_execs"] += 1
        results: list[Any] = []
        for op, args in self._ops:
            if op == "incrby":
                key, amount = args
                self._client.store[key] = self._client.store.get(key, 0) + amount
                results.append(self._client.store[key])
            elif op == "expire":
                key, ttl = args
                self._client.ttls[key] = ttl
                results.append(True)
        self._ops.clear()
        return results


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    """Inject the fake client into the counters module + reset the
    module-level ``_redis_client`` / ``_redis_disabled`` state."""
    fake = _FakeRedis()
    monkeypatch.setattr(counters, "_redis", lambda: fake)
    # Reset the module cache in case a prior test left it in a
    # disabled state.
    monkeypatch.setattr(counters, "_redis_client", None)
    monkeypatch.setattr(counters, "_redis_disabled", False)
    return fake


ORG_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# 1. Key format + TTL
# ---------------------------------------------------------------------------


async def test_counter_incr_creates_bucket_key(fake_redis: _FakeRedis):
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    # Exactly one key was written; shape is ``rep:{org}:...:{bucket}``.
    assert len(fake_redis.store) == 1
    (key,) = fake_redis.store.keys()
    assert key.startswith(f"rep:{ORG_ID}:platform_from:none:delivered:")
    assert fake_redis.store[key] == 1


async def test_counter_incr_uses_domain_id_for_own_domain_key(
    fake_redis: _FakeRedis,
):
    """``own_domain`` writes carry the domain UUID in the key so a
    per-domain read doesn't collide with a per-org platform_from
    read."""
    domain_id = uuid.uuid4()
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="own_domain",
        domain_id=domain_id,
        event="bounced",
    )
    (key,) = fake_redis.store.keys()
    assert f":own_domain:{domain_id}:" in key


async def test_counter_incr_sets_ttl_25h(fake_redis: _FakeRedis):
    """Every INCR pushes a fresh 25h TTL — 24h window + 1h grace so
    the trim sweep sees the last bucket before Redis expires it."""
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="complained",
    )
    (ttl_key,) = fake_redis.ttls.keys()
    assert fake_redis.ttls[ttl_key] == 25 * 3600


async def test_counter_incr_amount_parameter(fake_redis: _FakeRedis):
    """``amount`` param lets a caller batch-bump (e.g. Mailgun event
    replay). Default is +1."""
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
        amount=17,
    )
    (val,) = fake_redis.store.values()
    assert val == 17


# ---------------------------------------------------------------------------
# 2. Read semantics
# ---------------------------------------------------------------------------


async def test_counter_sum_last_24h_pipelines_24_buckets(
    fake_redis: _FakeRedis,
):
    """One ``sum_last_24h`` call = one MGET with exactly 24 keys."""
    result = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert result == 0  # no writes yet
    assert len(fake_redis.calls["mget_batches"]) == 1
    assert len(fake_redis.calls["mget_batches"][0]) == counters.BUCKETS_PER_WINDOW == 24


async def test_counter_sum_last_24h_reads_recent_writes(fake_redis: _FakeRedis):
    """Writes to the current-hour bucket appear in the next sum."""
    for _ in range(5):
        await counters.incr_counter(
            org_id=ORG_ID,
            envelope="platform_from",
            domain_id=None,
            event="delivered",
        )
    total = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert total == 5


async def test_counter_sum_excludes_bucket_older_than_24h(
    fake_redis: _FakeRedis,
):
    """A bucket key with a hour-index 25 hours ago is NOT summed —
    the read window is exactly 24 buckets back from now."""
    now_bucket = int(time.time() / 3600)
    stale_key = f"rep:{ORG_ID}:platform_from:none:delivered:{now_bucket - 25}"
    fresh_key = f"rep:{ORG_ID}:platform_from:none:delivered:{now_bucket}"
    fake_redis.store[stale_key] = 999  # would blow up the sum if read
    fake_redis.store[fresh_key] = 3

    total = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert total == 3
    # Sanity: the stale key was NOT in the MGET batch.
    (batch,) = fake_redis.calls["mget_batches"]
    assert stale_key not in batch


# ---------------------------------------------------------------------------
# 3. Concurrency
# ---------------------------------------------------------------------------


async def test_counter_concurrent_incr_atomic(fake_redis: _FakeRedis):
    """N concurrent INCRs on the same (org, envelope, event, bucket)
    add up to N — pipeline INCRBY is atomic. Runs 50 gathers to
    push past any accidental read-modify-write pattern."""
    import asyncio

    N = 50

    async def _one():
        await counters.incr_counter(
            org_id=ORG_ID,
            envelope="platform_from",
            domain_id=None,
            event="delivered",
        )

    await asyncio.gather(*(_one() for _ in range(N)))
    total = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert total == N
    # 50 writes = 50 pipeline execute calls.
    assert fake_redis.calls["pipeline_execs"] == N


# ---------------------------------------------------------------------------
# 4. Fail-soft behaviour
# ---------------------------------------------------------------------------


async def test_counter_incr_fail_soft_on_redis_error(fake_redis: _FakeRedis):
    """A Redis outage during INCR must NOT propagate — the send-gate
    would wedge under a Redis blip. The counter drift is logged."""
    fake_redis.raise_on_pipeline_execute = True
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )  # must not raise
    assert fake_redis.store == {}


async def test_counter_sum_fail_soft_returns_zero_on_redis_error(
    fake_redis: _FakeRedis,
):
    """A Redis outage during MGET returns 0 (the event-floor check
    catches this case before ratios fire)."""
    fake_redis.raise_on_mget = True
    total = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert total == 0


async def test_counter_returns_zero_when_redis_client_none(monkeypatch):
    """Redis client never constructed (dev shell without Redis) → 0
    reads, silent writes. Send-gate keeps working."""
    monkeypatch.setattr(counters, "_redis", lambda: None)
    await counters.incr_counter(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    total = await counters.sum_last_24h(
        org_id=ORG_ID,
        envelope="platform_from",
        domain_id=None,
        event="delivered",
    )
    assert total == 0


# ---------------------------------------------------------------------------
# 5. Trim sweep
# ---------------------------------------------------------------------------


async def test_trim_older_than_24h_deletes_stale_buckets(
    fake_redis: _FakeRedis,
):
    """Manually-seeded stale keys are deleted; fresh keys survive."""
    now_bucket = int(time.time() / 3600)
    stale_key = f"rep:{ORG_ID}:platform_from:none:delivered:{now_bucket - 30}"
    fresh_key = f"rep:{ORG_ID}:platform_from:none:delivered:{now_bucket}"
    fake_redis.store[stale_key] = 5
    fake_redis.store[fresh_key] = 7

    deleted = await counters.trim_older_than_24h_all_orgs()
    assert deleted == 1
    assert stale_key not in fake_redis.store
    assert fresh_key in fake_redis.store
