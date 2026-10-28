"""Sync orchestration layer.

Three concerns live here:

  1. **Enqueue helpers** — `enqueue_backfill / enqueue_incremental /
     enqueue_renewal`. The router callbacks (Steps 2 + 3) + push
     webhook handlers + Step 4's poll fallback call these instead
     of importing Celery tasks directly. Keeps the request path
     decoupled from the worker module so a partial Celery
     misconfiguration can't 500 the connect flow.

  2. **Per-account Redis lock** — `account_lock(account_id)`
     acquires a `SET … NX EX 300` lock keyed on `email_sync:{id}`.
     Prevents the same incremental sync from running twice when a
     push notification races the 60-second poll.

  3. **Inbound-message handler registry** — Step 5's conversations
     email adapter will register its handler via
     `register_inbound_handler(...)`. Step 4 dispatches every
     matched message through `dispatch_inbound(...)` which is a
     no-op (with a log line) when no handler is registered. Lets
     Steps 4 + 5 ship in either order.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from config import (
    REDIS_DB_BROKER,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)
from src.app.core.email.models import EmailAccount

logger = logging.getLogger(__name__)


# Lock TTL: long enough that the longest plausible incremental sync
# (a backlogged delta walk) finishes before expiry, short enough
# that a crashed worker leaves no stale lock for more than ~5 min.
_LOCK_TTL_SECONDS = 300


# --- Redis client (lazy module-level) ------------------------------------


_redis_client: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    """Lazy module-level Redis client. Connection is reused across
    locks in the same process; the broker DB is shared with Celery's
    own broker connection (different keyspace prefix)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            db=REDIS_DB_BROKER,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return _redis_client


# --- Enqueue helpers -----------------------------------------------------


def enqueue_backfill(account_id: uuid.UUID) -> None:
    """Fire-and-forget enqueue of the per-account backfill task.
    Called from the OAuth-callback handlers (Steps 2 + 3) right
    after the `email_accounts` row is upserted.

    The import is local so a Celery import failure (broker down,
    misconfigured worker) can't 500 the connect-flow router."""
    try:
        from src.app.core.email.tasks import backfill_account

        backfill_account.delay(str(account_id))
    except Exception:
        logger.exception(
            "enqueue_backfill failed for account=%s — connect proceeded",
            account_id,
        )


def enqueue_incremental(account_id: uuid.UUID) -> None:
    """Fire-and-forget enqueue of the per-account incremental sync.
    Called from the push webhook handlers (Steps 2 + 3) AND the
    60-second poll fallback. The Redis lock inside the task itself
    deduplicates same-account races."""
    try:
        from src.app.core.email.tasks import sync_account_incremental

        sync_account_incremental.delay(str(account_id))
    except Exception:
        logger.exception(
            "enqueue_incremental failed for account=%s",
            account_id,
        )


def enqueue_renewal(account_id: uuid.UUID) -> None:
    """Fire-and-forget enqueue of the per-account watch/subscription
    renewal task. The dispatcher inside picks the right provider
    routine (Gmail `users.watch` vs Microsoft `subscriptions.patch`)."""
    try:
        from src.app.core.email.tasks import renew_account_watch

        renew_account_watch.delay(str(account_id))
    except Exception:
        logger.exception("enqueue_renewal failed for account=%s", account_id)


# --- Per-account lock ----------------------------------------------------


@asynccontextmanager
async def account_lock(account_id: uuid.UUID):
    """`SET email_sync:{id} 1 NX EX 300` — yields True if the lock
    was acquired (caller proceeds), False if another worker already
    holds it (caller no-ops with a log line).

    Releases on context exit unless the TTL fired first. A crashed
    worker that fails to release just leaves the lock for at most
    300 seconds; the next attempt picks up cleanly."""
    key = f"email_sync:{account_id}"
    client = _redis()
    try:
        acquired = await client.set(key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception:
        # Redis transient failure — fail open. Better to risk a
        # double-sync (idempotent because the cursor + matched-set
        # are deterministic) than to drop the sync entirely.
        logger.exception(
            "account_lock: Redis SET failed for %s — failing open",
            account_id,
        )
        yield True
        return
    if not acquired:
        yield False
        return
    try:
        yield True
    finally:
        try:
            await client.delete(key)
        except Exception:
            logger.exception(
                "account_lock: Redis DEL failed for %s (lock expires via TTL anyway)",
                account_id,
            )


# --- Inbound handler registry (Step 5 hook) -----------------------------


InboundHandler = Callable[
    [EmailAccount, dict],
    Awaitable[None],
]
"""Signature Step 5's conversations email adapter will satisfy:
  - account: the row the matched message came from.
  - matched: a dict shape neutral across providers
              `{provider, message_id, conversation_id, headers,
                contact_id, raw_b64 (optional)}`.
Returns nothing; Step 5 persists messages + activities and emits
notifications.
"""


_inbound_handler: InboundHandler | None = None


def register_inbound_handler(handler: InboundHandler) -> None:
    """Step 5 calls this at import time to plug its adapter in.
    Step 4 ships with no handler — matched messages get logged and
    discarded until Step 5 lands."""
    global _inbound_handler
    _inbound_handler = handler


def _clear_inbound_handler_for_tests() -> None:
    global _inbound_handler
    _inbound_handler = None


async def dispatch_inbound(account: EmailAccount, matched: dict) -> None:
    """Hand a matched message to the registered handler. No-op +
    log when no handler is registered (Step 5 not yet shipped)."""
    if _inbound_handler is None:
        logger.debug(
            "dispatch_inbound: no handler registered; account=%s message_id=%s",
            account.id,
            matched.get("message_id"),
        )
        return
    try:
        await _inbound_handler(account, matched)
    except Exception:
        logger.exception(
            "inbound handler failed for account=%s message_id=%s",
            account.id,
            matched.get("message_id"),
        )


__all__ = [
    "InboundHandler",
    "account_lock",
    "dispatch_inbound",
    "enqueue_backfill",
    "enqueue_incremental",
    "enqueue_renewal",
    "register_inbound_handler",
]
