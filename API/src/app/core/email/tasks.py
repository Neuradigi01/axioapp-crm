"""Celery tasks for the email sync daemon.

Six tasks across three concerns:

  - **Per-account work** (triggered by enqueue helpers in
    `sync_daemon.py`):
      * `backfill_account(account_id)` — initial 30-day backfill
        on connect. Transitions sync_state pending→backfilling→live
        (or →error on failure).
      * `sync_account_incremental(account_id)` — push-or-poll
        triggered. Wrapped in a Redis lock to dedupe races.
      * `renew_account_watch(account_id)` — provider-dispatched
        watch/subscription renewal.

  - **Beat sweeps** (periodic):
      * `poll_fallback()` — every 60s. Queues incremental sync for
        live accounts whose `last_sync_at` is older than 5 minutes.
        Catches accounts whose push is unconfigured or briefly
        dropped notifications.
      * `scan_renewals()` — every 30 minutes. For Gmail accounts
        with watches expiring in < 24h AND Microsoft accounts with
        subscriptions expiring in < 24h, enqueue renewals.
      * `reset_daily_sent_counters()` — daily at 00:00 UTC. Zeroes
        every live account's `daily_sent_count` and stamps
        `daily_sent_reset_at`.

Convention: `@shared_task` wrapper synchronously calls
`asyncio.run(_async_helper(...))` per `src/celery/worker.py`'s
engine-reset hooks. Don't write `async def` tasks — they cannot be
called as `.delay()` and the prefork worker can't drive them.

All tasks run with NO tenant context. We open `async_session()`,
load the account via the unscoped helper, then `set_context(...)`
for the duration of the actual sync so RLS-protected reads
(contacts.email matching) work correctly.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from src.app.core.email.models import (
    EmailAccountProvider,
    EmailAccountSyncState,
)

log = logging.getLogger(__name__)


# Per-account error policy: 3 consecutive failures before we leave
# the row in `error` for the operator to investigate. Below the
# threshold the failure is logged + the row stays `live` so the
# next poll retries.
_MAX_CONSECUTIVE_ERRORS = 3
# Poll-fallback freshness: skip accounts synced within this window.
_POLL_FRESHNESS_WINDOW = timedelta(minutes=5)
# Renewal scan: enqueue renewal when watch/subscription expires
# within this window.
_RENEWAL_LEAD_TIME = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Per-account tasks
# ---------------------------------------------------------------------------


@shared_task(name="src.app.core.email.tasks.backfill_account")
def backfill_account(account_id: str) -> dict[str, Any]:
    """Initial backfill. Triggered by OAuth-callback handlers."""
    return asyncio.run(_backfill_account_async(uuid.UUID(account_id)))


async def _backfill_account_async(account_id: uuid.UUID) -> dict[str, Any]:
    from src.app.core.email import service as email_service
    from src.app.core.email.sync_daemon import dispatch_inbound
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    async with async_session() as session:
        account = await email_service.get_account_unscoped(session, account_id=account_id)
        if account is None:
            return {"skipped": "not_found", "account_id": str(account_id)}
        if account.sync_state == EmailAccountSyncState.disconnected:
            return {
                "skipped": "disconnected",
                "account_id": str(account_id),
            }

        ctx_token = set_context(RequestContext(org_id=account.org_id, user_id=account.user_id))
        try:
            account.sync_state = EmailAccountSyncState.backfilling
            account.last_sync_error = None
            await session.commit()
            await session.refresh(account)

            try:
                result = await _provider_backfill(account, session)
            except Exception as exc:
                account.sync_state = EmailAccountSyncState.error
                account.last_sync_error = str(exc)[:500]
                await session.commit()
                log.exception("backfill_account failed account=%s", account_id)
                return {
                    "error": str(exc)[:200],
                    "account_id": str(account_id),
                }

            # Hand each matched message to Step 5's handler (no-op
            # until Step 5 ships).
            for m in result.matched:
                await dispatch_inbound(account, _normalise_match(account, m))

            if result.new_cursor:
                account.sync_cursor = result.new_cursor
            account.sync_state = EmailAccountSyncState.live
            account.last_sync_at = datetime.now(UTC)
            account.last_sync_error = None
            await session.commit()

            log.info(
                "backfill_account ok account=%s matched=%d scanned=%d",
                account_id,
                len(result.matched),
                result.scanned_count,
            )
            return {
                "account_id": str(account_id),
                "matched": len(result.matched),
                "scanned": result.scanned_count,
                "truncated": result.truncated,
            }
        finally:
            reset_context(ctx_token)


@shared_task(name="src.app.core.email.tasks.sync_account_incremental")
def sync_account_incremental(account_id: str) -> dict[str, Any]:
    """Incremental sync. Triggered by push webhooks + poll fallback.
    Wrapped in a Redis lock to dedupe races."""
    return asyncio.run(_sync_account_incremental_async(uuid.UUID(account_id)))


async def _sync_account_incremental_async(
    account_id: uuid.UUID,
) -> dict[str, Any]:
    from src.app.core.email import service as email_service
    from src.app.core.email.sync_daemon import (
        account_lock,
        dispatch_inbound,
    )
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    async with account_lock(account_id) as acquired:
        if not acquired:
            log.info(
                "sync_account_incremental skipped (lock held) account=%s",
                account_id,
            )
            return {
                "skipped": "lock_held",
                "account_id": str(account_id),
            }

        async with async_session() as session:
            account = await email_service.get_account_unscoped(session, account_id=account_id)
            if account is None:
                return {"skipped": "not_found"}
            if account.sync_state != EmailAccountSyncState.live:
                return {
                    "skipped": f"state={account.sync_state.value}",
                    "account_id": str(account_id),
                }
            if not account.sync_cursor:
                # No cursor — caller should have run backfill first.
                # Self-heal by triggering one inline.
                log.warning(
                    "sync_account_incremental: no cursor for account=%s — running backfill instead",
                    account_id,
                )
                return await _backfill_account_async(account_id)

            ctx_token = set_context(RequestContext(org_id=account.org_id, user_id=account.user_id))
            try:
                try:
                    result = await _provider_incremental(account, session)
                except Exception as exc:
                    account.last_sync_error = str(exc)[:500]
                    # Soft-fail: keep state=live. The poll fallback
                    # will retry. Three consecutive failures will be
                    # observable via `last_sync_error` set without
                    # `last_sync_at` advancing.
                    await session.commit()
                    log.exception(
                        "sync_account_incremental failed account=%s",
                        account_id,
                    )
                    return {
                        "error": str(exc)[:200],
                        "account_id": str(account_id),
                    }

                # Provider-specific delta-expired handling.
                if getattr(result, "delta_link_expired", False):
                    log.info(
                        "delta link expired for account=%s — triggering full re-backfill",
                        account_id,
                    )
                    account.sync_cursor = None
                    await session.commit()
                    return await _backfill_account_async(account_id)

                for m in result.matched:
                    await dispatch_inbound(account, _normalise_match(account, m))

                if result.new_cursor:
                    account.sync_cursor = result.new_cursor
                account.last_sync_at = datetime.now(UTC)
                account.last_sync_error = None
                await session.commit()

                log.info(
                    "sync_account_incremental ok account=%s matched=%d scanned=%d",
                    account_id,
                    len(result.matched),
                    result.scanned_count,
                )
                return {
                    "account_id": str(account_id),
                    "matched": len(result.matched),
                    "scanned": result.scanned_count,
                }
            finally:
                reset_context(ctx_token)


@shared_task(name="src.app.core.email.tasks.renew_account_watch")
def renew_account_watch(account_id: str) -> dict[str, Any]:
    """Provider-aware watch / subscription renewal."""
    return asyncio.run(_renew_account_watch_async(uuid.UUID(account_id)))


async def _renew_account_watch_async(
    account_id: uuid.UUID,
) -> dict[str, Any]:
    from src.app.core.email import service as email_service
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    async with async_session() as session:
        account = await email_service.get_account_unscoped(session, account_id=account_id)
        if account is None:
            return {"skipped": "not_found"}
        if account.sync_state != EmailAccountSyncState.live:
            return {"skipped": f"state={account.sync_state.value}"}

        ctx_token = set_context(RequestContext(org_id=account.org_id, user_id=account.user_id))
        try:
            if account.provider == EmailAccountProvider.gmail:
                # Gmail re-issues `users.watch` to extend the
                # subscription. Sets a fresh historyId — we capture
                # it and update the cursor.
                from src.app.core.email.gmail import push as gmail_push

                history_id = await gmail_push.watch_if_configured(account, session)
                if history_id:
                    account.sync_cursor = history_id
                    await session.commit()
                    return {
                        "renewed": "gmail",
                        "account_id": str(account_id),
                    }
                return {
                    "skipped": "no_topic_configured",
                    "account_id": str(account_id),
                }

            if account.provider == EmailAccountProvider.microsoft:
                from src.app.core.email.microsoft import (
                    webhook as ms_webhook,
                )

                if not account.sync_cursor:
                    return {"skipped": "no_subscription_id"}
                new_exp = await ms_webhook.renew_subscription(
                    account,
                    session,
                    subscription_id=account.sync_cursor,
                )
                if new_exp is None:
                    return {
                        "skipped": "renewal_failed",
                        "account_id": str(account_id),
                    }
                return {
                    "renewed": "microsoft",
                    "account_id": str(account_id),
                    "new_expiration": new_exp,
                }
            return {"skipped": f"unknown_provider={account.provider}"}
        finally:
            reset_context(ctx_token)


# ---------------------------------------------------------------------------
# Beat sweeps
# ---------------------------------------------------------------------------


@shared_task(name="src.app.core.email.tasks.poll_fallback")
def poll_fallback() -> dict[str, Any]:
    """Every 60s — enqueue incremental sync for live accounts whose
    `last_sync_at` is stale (> 5 minutes). Catches accounts where
    push isn't configured or briefly dropped notifications."""
    return asyncio.run(_poll_fallback_async())


async def _poll_fallback_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.core.email.sync_daemon import enqueue_incremental
    from src.app.shared.db import async_session

    cutoff = datetime.now(UTC) - _POLL_FRESHNESS_WINDOW
    async with async_session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM tbl_email_accounts
                    WHERE sync_state = 'live'
                      AND sync_cursor IS NOT NULL
                      AND (last_sync_at IS NULL OR last_sync_at < :cutoff)
                    LIMIT 500
                    """
                ),
                {"cutoff": cutoff},
            )
        ).all()

    for (aid,) in rows:
        enqueue_incremental(aid)

    return {"enqueued": len(rows)}


@shared_task(name="src.app.core.email.tasks.sweep_stuck_pending")
def sweep_stuck_pending() -> dict[str, Any]:
    """Every 60s — recover email accounts stuck in ``sync_state='pending'``
    past the freshness window.

    Why this exists: ``sync_daemon.enqueue_backfill`` is a fire-and-
    forget wrapper — if Redis / the Celery broker was blipping during
    the OAuth callback, the ``backfill_account.delay()`` swallows the
    connection error + the row stays ``pending`` forever, so
    ``resolve_org_sender`` never picks the account up + workflow email
    sends silently skip with ``org_sender_not_configured``. Ajay's
    Workspace hit this on 2026-08-04 (see
    ``memory/project_workflows_absorb_automation.md``); we hand-flipped
    his ``sync_state`` to unblock, but every future OAuth completion
    would have the same silent-fail exposure.

    Sweep logic: find every non-disconnected account still ``pending``
    older than 5 minutes (long enough that the connect-flow's initial
    enqueue would have completed on a healthy broker) and re-enqueue
    backfill. The backfill task is idempotent — a duplicate on an
    already-transitioning row is a no-op. Cap at 200/tick to bound
    wall-clock; a healthy environment should never accumulate more
    than a handful in a minute.
    """
    return asyncio.run(_sweep_stuck_pending_async())


async def _sweep_stuck_pending_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.core.email.sync_daemon import enqueue_backfill
    from src.app.shared.db import async_session

    cutoff = datetime.now(UTC) - _POLL_FRESHNESS_WINDOW
    async with async_session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id
                      FROM tbl_email_accounts
                     WHERE sync_state = 'pending'
                       AND disconnected_at IS NULL
                       AND (connected_at IS NULL OR connected_at < :cutoff)
                     LIMIT 200
                    """
                ),
                {"cutoff": cutoff},
            )
        ).all()

    for (aid,) in rows:
        enqueue_backfill(aid)

    if rows:
        log.info("email.sweep_stuck_pending re-enqueued=%d", len(rows))
    return {"enqueued": len(rows)}


@shared_task(name="src.app.core.email.tasks.scan_renewals")
def scan_renewals() -> dict[str, Any]:
    """Every 30 min — enqueue renewal for accounts whose
    watch/subscription expires within 24 hours.

    For Gmail: we don't store an absolute expiry — Gmail's watch
    silently expires at 7 days. Proxy: enqueue renewal for any live
    Gmail account whose `last_sync_at` was > 5 days ago. The renewal
    call is cheap and idempotent.

    For Microsoft: subscription expiry is the actual Graph
    expirationDateTime we got back. v1 doesn't store it explicitly
    — we use a proxy: every live Microsoft account gets renewed if
    last_sync_at > 2 days ago. The renewal call is cheap.
    """
    return asyncio.run(_scan_renewals_async())


async def _scan_renewals_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.core.email.sync_daemon import enqueue_renewal
    from src.app.shared.db import async_session

    gmail_cutoff = datetime.now(UTC) - timedelta(days=5)
    ms_cutoff = datetime.now(UTC) - timedelta(days=2)
    async with async_session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, provider FROM tbl_email_accounts
                    WHERE sync_state = 'live'
                      AND sync_cursor IS NOT NULL
                      AND (
                        (provider = 'gmail' AND
                         (last_sync_at IS NULL OR last_sync_at < :gmail_cutoff))
                        OR
                        (provider = 'microsoft' AND
                         (last_sync_at IS NULL OR last_sync_at < :ms_cutoff))
                      )
                    LIMIT 500
                    """
                ),
                {
                    "gmail_cutoff": gmail_cutoff,
                    "ms_cutoff": ms_cutoff,
                },
            )
        ).all()
    for aid, _provider in rows:
        enqueue_renewal(aid)
    return {"enqueued": len(rows)}


@shared_task(name="src.app.core.email.tasks.reset_daily_sent_counters")
def reset_daily_sent_counters() -> dict[str, Any]:
    """Midnight UTC — zero every account's `daily_sent_count` and
    stamp `daily_sent_reset_at`. Idempotent."""
    return asyncio.run(_reset_daily_sent_counters_async())


async def _reset_daily_sent_counters_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.shared.db import async_session

    async with async_session() as session:
        result = await session.execute(
            text(
                """
                UPDATE tbl_email_accounts
                SET daily_sent_count = 0,
                    daily_sent_reset_at = now()
                WHERE sync_state != 'disconnected'
                  AND daily_sent_count > 0
                """
            )
        )
        await session.commit()
    rowcount = getattr(result, "rowcount", 0) or 0
    log.info("reset_daily_sent_counters reset=%d", rowcount)
    return {"reset": rowcount}


# ---------------------------------------------------------------------------
# Provider dispatch helpers
# ---------------------------------------------------------------------------


async def _provider_backfill(account, session):
    """Dispatch to the right provider's `backfill` based on
    `account.provider`. Returns the provider's `SyncResult`."""
    if account.provider == EmailAccountProvider.gmail:
        from src.app.core.email.gmail import sync as gmail_sync

        return await gmail_sync.backfill(account, session, days=30)
    if account.provider == EmailAccountProvider.microsoft:
        from src.app.core.email.microsoft import sync as ms_sync

        return await ms_sync.backfill(account, session, days=30)
    raise RuntimeError(f"unknown email provider: {account.provider}")


async def _provider_incremental(account, session):
    """Dispatch to the right provider's `sync_incremental`."""
    if account.provider == EmailAccountProvider.gmail:
        from src.app.core.email.gmail import sync as gmail_sync

        return await gmail_sync.sync_incremental(account, session)
    if account.provider == EmailAccountProvider.microsoft:
        from src.app.core.email.microsoft import sync as ms_sync

        return await ms_sync.sync_incremental(account, session)
    raise RuntimeError(f"unknown email provider: {account.provider}")


def _normalise_match(account, matched) -> dict:
    """Flatten a provider-specific MatchedMessage into the
    provider-neutral dict shape Step 5's handler consumes."""
    # Gmail and Microsoft each carry slightly different ids on the
    # MatchedMessage dataclass; normalise here so the inbound
    # handler doesn't have to know which one it got.
    if is_dataclass(matched):
        data = asdict(matched)
    elif isinstance(matched, dict):
        data = dict(matched)
    else:
        # Best-effort attribute scrape for an unexpected shape.
        data = {
            "gmail_message_id": getattr(matched, "gmail_message_id", None),
            "graph_message_id": getattr(matched, "graph_message_id", None),
            "headers": getattr(matched, "headers", {}),
            "matched_contact_id": getattr(matched, "matched_contact_id", None),
        }

    return {
        "provider": account.provider.value,
        "message_id": data.get("gmail_message_id") or data.get("graph_message_id"),
        "conversation_id": data.get("gmail_thread_id") or data.get("graph_conversation_id"),
        "headers": data.get("headers", {}),
        "contact_id": data.get("matched_contact_id"),
        "raw_b64": None,
    }


__all__ = [
    "backfill_account",
    "poll_fallback",
    "renew_account_watch",
    "reset_daily_sent_counters",
    "scan_renewals",
    "sweep_stuck_pending",
    "sync_account_incremental",
]
