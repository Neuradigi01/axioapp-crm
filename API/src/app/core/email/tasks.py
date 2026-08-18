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
    EmailAccount,
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
# Stuck-backfill recovery cutoff. The per-account backfill has a
# 30-min hard time limit (see `backfill_account` above); we wait a
# small buffer past that before treating a `backfilling` row as
# abandoned (worker SIGKILL, docker restart, host reboot — none of
# which trigger the BaseException cleanup below).
_BACKFILLING_STUCK_CUTOFF = timedelta(minutes=40)
# Stuck-error recovery cutoff. A transient Gmail/Graph blip flips the
# row to `error`; retrying every 15 min turns those into a self-
# healing account without spamming a genuinely-revoked one.
_ERROR_RETRY_CUTOFF = timedelta(minutes=15)
# Renewal scan: enqueue renewal when watch/subscription expires
# within this window.
_RENEWAL_LEAD_TIME = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Per-account tasks
# ---------------------------------------------------------------------------


@shared_task(
    name="src.app.core.email.tasks.backfill_account",
    # Override the global 240s soft / 300s hard limits (celery_config.py).
    # A first-connect 30-day backfill on a busy mailbox fetches metadata
    # for every message one-at-a-time (~400ms/msg); real inboxes routinely
    # need 10+ minutes. Hitting the global soft limit killed the task
    # mid-scan and left the row stuck at sync_state='backfilling'.
    soft_time_limit=1500,
    time_limit=1800,
)
def backfill_account(account_id: str) -> dict[str, Any]:
    """Initial backfill. Triggered by OAuth-callback handlers."""
    return asyncio.run(_backfill_account_async(uuid.UUID(account_id)))


async def _backfill_account_async(account_id: uuid.UUID) -> dict[str, Any]:
    from src.app.core.email import service as email_service
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    # Cross-tenant bootstrap read to learn org_id → sync_state.
    # `get_account_unscoped` returns a *transient* EmailAccount hand-
    # built from raw SQL rows (see data_access.get_account_by_id_unscoped)
    # — it is NOT attached to the session, so mutations on it never
    # flush and `session.refresh()` raises InvalidRequestError. We use
    # it only to learn (org_id, user_id, sync_state), then re-load
    # via ORM under the tenant context to get a persistent instance.
    async with async_session() as bootstrap:
        transient = await email_service.get_account_unscoped(bootstrap, account_id=account_id)
    if transient is None:
        return {"skipped": "not_found", "account_id": str(account_id)}
    if transient.sync_state == EmailAccountSyncState.disconnected:
        return {
            "skipped": "disconnected",
            "account_id": str(account_id),
        }

    ctx_token = set_context(RequestContext(org_id=transient.org_id, user_id=transient.user_id))
    try:
        async with async_session() as session:
            account = await session.get(EmailAccount, account_id)
            if account is None:
                return {"skipped": "not_found", "account_id": str(account_id)}

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

            # Enrich each match with body_text + raw_b64, then hand
            # to Step 5's handler. The provider sync primitives return
            # metadata-only records to keep the scan cheap — body is
            # fetched here, once per match.
            await _dispatch_matched_messages(account, session, result.matched)

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
    except BaseException:
        # Celery's ``SoftTimeLimitExceeded`` and worker SIGKILL from the
        # hard time limit both bypass our inner ``except Exception`` (the
        # signal is raised outside the async frame). Without cleanup the
        # row is left at ``sync_state='backfilling'`` — the sweeper only
        # rescues ``pending`` rows, so the account stays permanently
        # stuck and workflow email sends skip it. Flip to ``error`` so
        # the operator sees why + a re-connect can start fresh.
        try:
            async with async_session() as recover:
                stuck = await recover.get(EmailAccount, account_id)
                if stuck is not None and stuck.sync_state == EmailAccountSyncState.backfilling:
                    stuck.sync_state = EmailAccountSyncState.error
                    stuck.last_sync_error = "backfill aborted (time limit or worker kill)"
                    await recover.commit()
        except Exception:
            log.exception("backfill_account cleanup failed account=%s", account_id)
        raise
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
    from src.app.core.email.sync_daemon import account_lock
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

        # Cross-tenant bootstrap read — the returned instance is
        # transient (raw SQL, not session-attached). We only use it to
        # learn org_id and gate on sync_state; the real work runs on a
        # fresh persistent instance loaded under the tenant context so
        # commit()s actually flush.
        async with async_session() as bootstrap:
            transient = await email_service.get_account_unscoped(bootstrap, account_id=account_id)
        if transient is None:
            return {"skipped": "not_found"}
        if transient.sync_state != EmailAccountSyncState.live:
            return {
                "skipped": f"state={transient.sync_state.value}",
                "account_id": str(account_id),
            }
        if not transient.sync_cursor:
            # No cursor — caller should have run backfill first.
            # Self-heal by triggering one inline.
            log.warning(
                "sync_account_incremental: no cursor for account=%s — running backfill instead",
                account_id,
            )
            return await _backfill_account_async(account_id)

        ctx_token = set_context(RequestContext(org_id=transient.org_id, user_id=transient.user_id))
        try:
            async with async_session() as session:
                account = await session.get(EmailAccount, account_id)
                if account is None:
                    return {"skipped": "not_found", "account_id": str(account_id)}
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

                await _dispatch_matched_messages(account, session, result.matched)

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

    # Cross-tenant bootstrap read — the returned instance is transient
    # (raw SQL, not session-attached). We only use it to learn org_id
    # and gate on sync_state; the real work runs on a fresh persistent
    # instance loaded under the tenant context so commit()s actually flush.
    async with async_session() as bootstrap:
        transient = await email_service.get_account_unscoped(bootstrap, account_id=account_id)
    if transient is None:
        return {"skipped": "not_found"}
    if transient.sync_state != EmailAccountSyncState.live:
        return {"skipped": f"state={transient.sync_state.value}"}

    ctx_token = set_context(RequestContext(org_id=transient.org_id, user_id=transient.user_id))
    try:
        async with async_session() as session:
            account = await session.get(EmailAccount, account_id)
            if account is None:
                return {"skipped": "not_found", "account_id": str(account_id)}

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
    """Every 60s — recover email accounts stuck outside ``sync_state='live'``
    past the per-state freshness window.

    Why this exists: ``sync_daemon.enqueue_backfill`` is a fire-and-
    forget wrapper — if Redis / the Celery broker was blipping during
    the OAuth callback, the ``backfill_account.delay()`` swallows the
    connection error + the row stays ``pending`` forever. Ajay's
    Workspace hit this on 2026-08-04 (see
    ``memory/project_workflows_absorb_automation.md``); we hand-flipped
    his ``sync_state`` to unblock, but every future OAuth completion
    would have the same silent-fail exposure. Symptom is always the
    same: ``resolve_org_sender`` never picks the account up + workflow
    email sends silently skip with ``org_sender_not_configured``.

    Three non-live states can leave an account stuck; each has its own
    cutoff:

      * ``pending`` — enqueue was lost (broker blip). Recover after
        5 min (long enough that a healthy enqueue would have started
        the task).
      * ``backfilling`` — worker was killed mid-run (docker restart,
        SIGKILL, host reboot). The BaseException cleanup at the top of
        this file only fires when the async frame terminates, so a
        cold kill leaves the row here. Recover after 40 min (past the
        30-min hard time-limit plus buffer).
      * ``error`` — a real backfill exception. Retry after 15 min so a
        transient Gmail/Graph blip self-heals; a genuinely revoked
        account will keep bouncing back to ``error`` on each attempt
        (operator sees ``last_sync_error`` and clicks Reconnect).

    ``disconnected`` rows are excluded — the operator explicitly
    revoked. The backfill task is idempotent, so a duplicate enqueue
    on an already-transitioning row is a no-op. Cap at 200/tick.
    """
    return asyncio.run(_sweep_stuck_pending_async())


async def _sweep_stuck_pending_async() -> dict[str, Any]:
    from sqlalchemy import text

    from src.app.core.email.sync_daemon import enqueue_backfill
    from src.app.shared.db import async_session

    now = datetime.now(UTC)
    pending_cutoff = now - _POLL_FRESHNESS_WINDOW
    backfilling_cutoff = now - _BACKFILLING_STUCK_CUTOFF
    error_cutoff = now - _ERROR_RETRY_CUTOFF
    async with async_session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, sync_state
                      FROM tbl_email_accounts
                     WHERE disconnected_at IS NULL
                       AND (
                            (sync_state = 'pending'
                             AND (connected_at IS NULL
                                  OR connected_at < :pending_cutoff))
                         OR (sync_state = 'backfilling'
                             AND (last_sync_at IS NULL
                                  OR last_sync_at < :backfilling_cutoff)
                             AND (connected_at IS NULL
                                  OR connected_at < :backfilling_cutoff))
                         OR (sync_state = 'error'
                             AND (last_sync_at IS NULL
                                  OR last_sync_at < :error_cutoff))
                       )
                     LIMIT 200
                    """
                ),
                {
                    "pending_cutoff": pending_cutoff,
                    "backfilling_cutoff": backfilling_cutoff,
                    "error_cutoff": error_cutoff,
                },
            )
        ).all()

    by_state: dict[str, int] = {}
    for aid, state in rows:
        enqueue_backfill(aid)
        by_state[state] = by_state.get(state, 0) + 1

    if rows:
        log.info(
            "email.sweep_stuck_pending re-enqueued=%d by_state=%s",
            len(rows),
            by_state,
        )
    return {"enqueued": len(rows), "by_state": by_state}


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


def _normalise_match(
    account,
    matched,
    *,
    body_text: str = "",
    raw_b64: str | None = None,
) -> dict:
    """Flatten a provider-specific MatchedMessage into the
    provider-neutral dict shape Step 5's handler consumes.

    ``body_text`` and ``raw_b64`` are populated by
    :func:`_fetch_body_for_match` before this is called (the provider
    sync primitives deliberately return metadata-only MatchedMessage
    records to keep the scan cheap; body fetch is a per-match cost
    paid only for the matched subset).
    """
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
        "body_text": body_text,
        "raw_b64": raw_b64,
    }


# Cap persisted body-text at 64 KB (well past the useful signal-to-
# noise threshold for CRM triage — reply text, opening line, key ask).
# Full raw MIME still lives on the payload column for audit / forensics.
_BODY_TEXT_MAX_CHARS = 64_000


def _extract_body_text_from_mime(raw_mime: bytes) -> str:
    """Parse raw RFC-822 bytes + return the best-effort plaintext body.

    Prefers ``text/plain`` (verbatim). Falls back to ``text/html`` with
    tags stripped when no plain part exists (marketing / rich-format
    email increasingly ships HTML-only). Returns "" on unparseable or
    empty payloads — caller falls back to the subject as bubble text.
    """
    from email import policy
    from email.parser import BytesParser

    if not raw_mime:
        return ""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_mime)
    except Exception:
        log.warning("email body parse failed; returning empty", exc_info=True)
        return ""

    plain_part = msg.get_body(preferencelist=("plain",))
    if plain_part is not None:
        try:
            content = plain_part.get_content()
            if isinstance(content, str) and content.strip():
                return content.strip()[:_BODY_TEXT_MAX_CHARS]
        except Exception:
            log.warning("email plain-part decode failed", exc_info=True)

    html_part = msg.get_body(preferencelist=("html",))
    if html_part is not None:
        try:
            html = html_part.get_content()
            if isinstance(html, str) and html.strip():
                import re as _re

                # Strip scripts/styles first (their content isn't
                # user-visible + often huge), then all remaining tags,
                # then collapse whitespace runs.
                stripped = _re.sub(
                    r"<(script|style)[^>]*>.*?</\1>",
                    " ",
                    html,
                    flags=_re.DOTALL | _re.IGNORECASE,
                )
                stripped = _re.sub(r"<[^>]+>", " ", stripped)
                stripped = _re.sub(r"\s+", " ", stripped).strip()
                if stripped:
                    return stripped[:_BODY_TEXT_MAX_CHARS]
        except Exception:
            log.warning("email html-part decode failed", exc_info=True)

    return ""


async def _fetch_body_for_match(account, session, matched) -> tuple[str, str | None]:
    """Fetch raw MIME for a MatchedMessage + extract plaintext body.

    Provider sync primitives fetch metadata only (cheap); this is the
    per-match body-fetch step. Returns ``(body_text, raw_b64)`` where
    ``raw_b64`` is the base64-encoded raw MIME (kept on the message
    payload for audit / re-parse). Both fall back to ``("", None)``
    when the provider fetch fails — the caller persists whatever it
    can (subject → bubble text) rather than dropping the whole message.
    """
    import base64

    if account.provider == EmailAccountProvider.gmail:
        from src.app.core.email.gmail.client import GmailClient, GmailHTTPError

        gmail_id = getattr(matched, "gmail_message_id", None) or (
            matched.get("gmail_message_id") if isinstance(matched, dict) else None
        )
        if not gmail_id:
            return "", None
        client = GmailClient(account=account, session=session)
        try:
            detail = await client.get_message(gmail_id, format="raw")
        except GmailHTTPError as exc:
            if exc.status_code == 404:
                return "", None
            log.warning(
                "gmail get_message(raw) failed account=%s msg=%s status=%s",
                account.id,
                gmail_id,
                exc.status_code,
            )
            return "", None
        except Exception:
            log.exception(
                "gmail get_message(raw) unexpected error account=%s msg=%s",
                account.id,
                gmail_id,
            )
            return "", None
        raw_b64url = detail.get("raw")
        if not isinstance(raw_b64url, str):
            return "", None
        try:
            raw_mime = base64.urlsafe_b64decode(raw_b64url)
        except Exception:
            log.warning("gmail raw base64url decode failed msg=%s", gmail_id, exc_info=True)
            return "", None
        body = _extract_body_text_from_mime(raw_mime)
        return body, base64.b64encode(raw_mime).decode("ascii")

    if account.provider == EmailAccountProvider.microsoft:
        from src.app.core.email.microsoft.client import GraphClient, GraphHTTPError

        graph_id = getattr(matched, "graph_message_id", None) or (
            matched.get("graph_message_id") if isinstance(matched, dict) else None
        )
        if not graph_id:
            return "", None
        client = GraphClient(account=account, session=session)
        try:
            raw_mime = await client.get_message_raw(graph_id)
        except GraphHTTPError as exc:
            if exc.status_code == 404:
                return "", None
            log.warning(
                "graph get_message_raw failed account=%s msg=%s status=%s",
                account.id,
                graph_id,
                exc.status_code,
            )
            return "", None
        except Exception:
            log.exception(
                "graph get_message_raw unexpected error account=%s msg=%s",
                account.id,
                graph_id,
            )
            return "", None
        if not raw_mime:
            return "", None
        body = _extract_body_text_from_mime(raw_mime)
        return body, base64.b64encode(raw_mime).decode("ascii")

    return "", None


async def _dispatch_matched_messages(account, session, matched_list) -> None:
    """Enrich every match with body_text + raw_b64, then hand to the
    inbound dispatcher. Extracted so the backfill + incremental paths
    can share the same body-fetch loop instead of duplicating it."""
    from src.app.core.email.sync_daemon import dispatch_inbound

    for m in matched_list:
        body_text, raw_b64 = await _fetch_body_for_match(account, session, m)
        await dispatch_inbound(
            account,
            _normalise_match(account, m, body_text=body_text, raw_b64=raw_b64),
        )


__all__ = [
    "backfill_account",
    "poll_fallback",
    "renew_account_watch",
    "reset_daily_sent_counters",
    "scan_renewals",
    "sweep_stuck_pending",
    "sync_account_incremental",
]
