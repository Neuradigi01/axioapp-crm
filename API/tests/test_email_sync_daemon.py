"""Step 4 — mailbox sync daemon tests.

Five groups:

  1. `enqueue_*` helpers — Celery import failures are swallowed (the
     connect-flow router must not 500 on a Celery misconfiguration).
  2. `account_lock` — Redis SET/NX semantics + fail-open on Redis
     transient error.
  3. `dispatch_inbound` + `register_inbound_handler` — Step 5 hook.
  4. `_normalise_match` — provider-neutral dict shape produced from
     Gmail vs Microsoft `MatchedMessage` dataclasses.
  5. `_backfill_account_async` + `_sync_account_incremental_async` —
     state-machine transitions (pending → backfilling → live;
     soft-fail on incremental error; delta-link expired → re-backfill).

Convention: no DB. Stub `email_service.get_account_unscoped` to
return a pre-built EmailAccount; stub the provider sync routines
to return canned SyncResult objects; stub session.commit / refresh.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.app.core.email import sync_daemon
from src.app.core.email import tasks as email_tasks
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)

_ORG_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_account(**overrides) -> EmailAccount:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        user_id=_USER_ID,
        provider=EmailAccountProvider.gmail,
        external_account_id="asha@example.com",
        email_address="asha@example.com",
        display_name="Asha",
        access_token_enc="enc",
        refresh_token_enc="enc",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes_granted=[],
        sync_cursor="history-100",
        sync_state=EmailAccountSyncState.pending,
        last_sync_at=None,
        last_sync_error=None,
        daily_sent_count=0,
        daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=UTC),
        connected_at=datetime(2026, 6, 1, tzinfo=UTC),
        disconnected_at=None,
        disconnected_by=None,
    )
    defaults.update(overrides)
    return EmailAccount(**defaults)


# --- 1. enqueue helpers --------------------------------------------------


class TestEnqueueHelpers:
    def test_enqueue_backfill_swallows_celery_import_failure(self, monkeypatch):
        """If Celery's import raises (broker down, etc.), the helper
        must log and return — the connect flow must keep working."""

        # Force the lazy import to raise by inserting a fake task.
        def boom(*_a, **_k):
            raise RuntimeError("celery broker down")

        fake_tasks = type("FakeMod", (), {})()
        fake_tasks.backfill_account = MagicMock()
        fake_tasks.backfill_account.delay = boom
        monkeypatch.setattr(
            "src.app.core.email.tasks.backfill_account",
            fake_tasks.backfill_account,
        )
        # Should not raise.
        sync_daemon.enqueue_backfill(uuid.uuid4())

    def test_enqueue_incremental_dispatches_delay(self, monkeypatch):
        called: list = []

        class _FakeTask:
            def delay(self, account_id: str) -> None:
                called.append(account_id)

        monkeypatch.setattr(
            "src.app.core.email.tasks.sync_account_incremental",
            _FakeTask(),
        )
        aid = uuid.uuid4()
        sync_daemon.enqueue_incremental(aid)
        assert called == [str(aid)]


# --- 2. account_lock ----------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[dict] = []
        self.delete_calls: list[str] = []

    async def set(self, key, value, *, nx=False, ex=None):
        self.set_calls.append({"key": key, "nx": nx, "ex": ex})
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.delete_calls.append(key)
        self.store.pop(key, None)


class _RedisRaisingSet(_FakeRedis):
    async def set(self, key, value, *, nx=False, ex=None):
        raise RuntimeError("redis down")


class TestAccountLock:
    @pytest.mark.asyncio
    async def test_first_holder_acquires_then_releases(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake)
        aid = uuid.uuid4()
        async with sync_daemon.account_lock(aid) as acquired:
            assert acquired is True
            assert f"email_sync:{aid}" in fake.store
        assert fake.delete_calls == [f"email_sync:{aid}"]

    @pytest.mark.asyncio
    async def test_second_holder_gets_false(self, monkeypatch):
        fake = _FakeRedis()
        fake.store[f"email_sync:{uuid.uuid4()}"] = "held"
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake)
        # Re-use same key by pre-loading.
        aid = uuid.uuid4()
        fake.store[f"email_sync:{aid}"] = "held"
        async with sync_daemon.account_lock(aid) as acquired:
            assert acquired is False
        # No delete call because we didn't acquire.
        assert f"email_sync:{aid}" not in fake.delete_calls

    @pytest.mark.asyncio
    async def test_redis_transient_failure_fails_open(self, monkeypatch):
        fake = _RedisRaisingSet()
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake)
        async with sync_daemon.account_lock(uuid.uuid4()) as acquired:
            # Fail-open: caller proceeds as if it had the lock.
            assert acquired is True


# --- 3. Inbound handler registry ----------------------------------------


class TestInboundHandler:
    @pytest.mark.asyncio
    async def test_dispatch_no_op_when_no_handler(self):
        sync_daemon._clear_inbound_handler_for_tests()
        # Should not raise.
        await sync_daemon.dispatch_inbound(_make_account(), {"message_id": "x"})

    @pytest.mark.asyncio
    async def test_dispatch_calls_registered_handler(self):
        sync_daemon._clear_inbound_handler_for_tests()
        seen: list = []

        async def handler(account, matched):
            seen.append((account.id, matched["message_id"]))

        sync_daemon.register_inbound_handler(handler)
        acc = _make_account()
        await sync_daemon.dispatch_inbound(acc, {"message_id": "m1"})
        assert seen == [(acc.id, "m1")]
        sync_daemon._clear_inbound_handler_for_tests()

    @pytest.mark.asyncio
    async def test_handler_exception_swallowed(self):
        sync_daemon._clear_inbound_handler_for_tests()

        async def handler(_a, _m):
            raise RuntimeError("step5 blew up")

        sync_daemon.register_inbound_handler(handler)
        # Daemon must not propagate the handler's exception.
        await sync_daemon.dispatch_inbound(_make_account(), {"message_id": "m1"})
        sync_daemon._clear_inbound_handler_for_tests()


# --- 4. _normalise_match ------------------------------------------------


class TestNormaliseMatch:
    def test_gmail_match(self):
        from src.app.core.email.gmail.sync import MatchedMessage

        acc = _make_account(provider=EmailAccountProvider.gmail)
        m = MatchedMessage(
            gmail_message_id="g-1",
            gmail_thread_id="thr-g",
            headers={"subject": "hi"},
            matched_contact_id=uuid.uuid4(),
        )
        flat = email_tasks._normalise_match(acc, m)
        assert flat["provider"] == "gmail"
        assert flat["message_id"] == "g-1"
        assert flat["conversation_id"] == "thr-g"
        assert flat["headers"] == {"subject": "hi"}
        assert flat["contact_id"] == m.matched_contact_id

    def test_microsoft_match(self):
        from src.app.core.email.microsoft.sync import MatchedMessage

        acc = _make_account(provider=EmailAccountProvider.microsoft)
        m = MatchedMessage(
            graph_message_id="ms-1",
            graph_conversation_id="conv-ms",
            headers={"subject": "hi"},
            matched_contact_id=uuid.uuid4(),
        )
        flat = email_tasks._normalise_match(acc, m)
        assert flat["provider"] == "microsoft"
        assert flat["message_id"] == "ms-1"
        assert flat["conversation_id"] == "conv-ms"
        assert flat["contact_id"] == m.matched_contact_id


# --- 5. Backfill + incremental state machine ----------------------------


@dataclass
class _FakeSyncResult:
    matched: list = field(default_factory=list)
    scanned_count: int = 0
    new_cursor: str | None = None
    truncated: bool = False
    delta_link_expired: bool = False


class _CapturingSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@asynccontextmanager
async def _yield_session(session):
    yield session


@pytest.fixture
def patch_session_ctx(monkeypatch):
    """Replace `async_session()` with a context that yields our
    capturing stub."""
    session = _CapturingSession()

    @asynccontextmanager
    async def fake_async_session():
        yield session

    monkeypatch.setattr("src.app.shared.db.async_session", fake_async_session)
    # tasks.py imports `async_session` lazily inside the helpers, so
    # we don't need to patch in tasks's own namespace.
    return session


@pytest.fixture
def patch_context(monkeypatch):
    """Stub out set_context / reset_context so our tests don't depend
    on the real RequestContext machinery."""
    tokens: list = []

    def set_context(ctx):
        tokens.append("set")
        return object()

    def reset_context(_token):
        tokens.append("reset")

    monkeypatch.setattr("src.app.shared.context.set_context", set_context)
    monkeypatch.setattr("src.app.shared.context.reset_context", reset_context)
    return tokens


@pytest.fixture(autouse=True)
def reset_inbound_handler():
    sync_daemon._clear_inbound_handler_for_tests()
    yield
    sync_daemon._clear_inbound_handler_for_tests()


class TestBackfillStateMachine:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_live(
        self, patch_session_ctx, patch_context, monkeypatch
    ):
        account = _make_account(sync_state=EmailAccountSyncState.pending)

        async def fake_loader(_session, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )

        async def fake_backfill(acc, sess):
            return _FakeSyncResult(
                matched=[],
                scanned_count=12,
                new_cursor="history-200",
            )

        monkeypatch.setattr(email_tasks, "_provider_backfill", fake_backfill)

        result = await email_tasks._backfill_account_async(account.id)
        assert result["matched"] == 0
        assert result["scanned"] == 12
        assert account.sync_state == EmailAccountSyncState.live
        assert account.sync_cursor == "history-200"
        assert account.last_sync_at is not None
        assert account.last_sync_error is None

    @pytest.mark.asyncio
    async def test_skips_disconnected_account(self, patch_session_ctx, patch_context, monkeypatch):
        account = _make_account(sync_state=EmailAccountSyncState.disconnected)

        async def fake_loader(_session, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )
        result = await email_tasks._backfill_account_async(account.id)
        assert result.get("skipped") == "disconnected"

    @pytest.mark.asyncio
    async def test_backfill_failure_transitions_to_error(
        self, patch_session_ctx, patch_context, monkeypatch
    ):
        account = _make_account(sync_state=EmailAccountSyncState.pending)

        async def fake_loader(_session, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )

        async def boom(_acc, _sess):
            raise RuntimeError("gmail quota exhausted")

        monkeypatch.setattr(email_tasks, "_provider_backfill", boom)
        result = await email_tasks._backfill_account_async(account.id)
        assert "error" in result
        assert account.sync_state == EmailAccountSyncState.error
        assert account.last_sync_error == "gmail quota exhausted"

    @pytest.mark.asyncio
    async def test_backfill_calls_inbound_handler_for_each_match(
        self, patch_session_ctx, patch_context, monkeypatch
    ):
        from src.app.core.email.gmail.sync import MatchedMessage

        account = _make_account(sync_state=EmailAccountSyncState.pending)

        async def fake_loader(_session, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )

        matches = [
            MatchedMessage(
                gmail_message_id=f"g-{i}",
                gmail_thread_id=f"thr-{i}",
                headers={},
                matched_contact_id=uuid.uuid4(),
            )
            for i in range(3)
        ]

        async def fake_backfill(_acc, _sess):
            return _FakeSyncResult(matched=matches, scanned_count=5, new_cursor="cursor-x")

        monkeypatch.setattr(email_tasks, "_provider_backfill", fake_backfill)

        seen: list = []

        async def handler(_a, matched):
            seen.append(matched["message_id"])

        sync_daemon.register_inbound_handler(handler)
        await email_tasks._backfill_account_async(account.id)
        assert seen == ["g-0", "g-1", "g-2"]


class TestIncrementalStateMachine:
    @pytest.mark.asyncio
    async def test_skips_when_not_live(self, patch_session_ctx, patch_context, monkeypatch):
        account = _make_account(
            sync_state=EmailAccountSyncState.error,
            sync_cursor="cur",
        )

        async def fake_loader(_session, *, account_id):
            return account

        # Acquire lock cleanly.
        fake_redis = _FakeRedis()
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake_redis)
        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )
        result = await email_tasks._sync_account_incremental_async(account.id)
        assert result["skipped"] == "state=error"

    @pytest.mark.asyncio
    async def test_lock_held_returns_skipped(self, monkeypatch):
        fake_redis = _FakeRedis()
        aid = uuid.uuid4()
        fake_redis.store[f"email_sync:{aid}"] = "held"
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake_redis)
        result = await email_tasks._sync_account_incremental_async(aid)
        assert result["skipped"] == "lock_held"

    @pytest.mark.asyncio
    async def test_delta_expired_triggers_rebackfill(
        self, patch_session_ctx, patch_context, monkeypatch
    ):
        account = _make_account(
            sync_state=EmailAccountSyncState.live,
            sync_cursor="delta://stale",
        )
        backfill_called: list = []

        async def fake_loader(_session, *, account_id):
            return account

        # Acquire lock cleanly.
        fake_redis = _FakeRedis()
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake_redis)
        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )

        async def fake_incremental(_acc, _sess):
            return _FakeSyncResult(delta_link_expired=True)

        async def fake_backfill_async(aid):
            backfill_called.append(aid)
            return {"backfilled": True}

        monkeypatch.setattr(email_tasks, "_provider_incremental", fake_incremental)
        monkeypatch.setattr(email_tasks, "_backfill_account_async", fake_backfill_async)

        result = await email_tasks._sync_account_incremental_async(account.id)
        assert result == {"backfilled": True}
        assert backfill_called == [account.id]
        # Cursor cleared on delta-expired before re-backfill.
        assert account.sync_cursor is None

    @pytest.mark.asyncio
    async def test_happy_incremental_advances_cursor(
        self, patch_session_ctx, patch_context, monkeypatch
    ):
        account = _make_account(
            sync_state=EmailAccountSyncState.live,
            sync_cursor="cur-old",
        )

        async def fake_loader(_session, *, account_id):
            return account

        fake_redis = _FakeRedis()
        monkeypatch.setattr(sync_daemon, "_redis", lambda: fake_redis)
        monkeypatch.setattr(
            "src.app.core.email.service.get_account_unscoped",
            fake_loader,
        )

        async def fake_incremental(_acc, _sess):
            return _FakeSyncResult(
                matched=[],
                scanned_count=4,
                new_cursor="cur-new",
            )

        monkeypatch.setattr(email_tasks, "_provider_incremental", fake_incremental)

        result = await email_tasks._sync_account_incremental_async(account.id)
        assert result["scanned"] == 4
        assert account.sync_cursor == "cur-new"
        assert account.last_sync_at is not None
        assert account.last_sync_error is None
