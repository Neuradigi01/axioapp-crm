"""Microsoft Graph change-notification primitives.

Graph's webhook model:
  1. Client (us) creates a subscription via `POST /subscriptions`
     with a `notificationUrl`, `resource` (`/me/messages` for the
     mailbox stream), `changeType`, `expirationDateTime`, and a
     `clientState` secret we choose.
  2. Graph immediately calls our webhook URL with `?validationToken
     =<rand>` — we MUST echo the token back as text/plain within
     ~10 seconds or the subscription is rejected.
  3. On every mailbox change, Graph POSTs a notification envelope:
       {value: [
         {subscriptionId, clientState, resource, changeType,
          resourceData: {id, "@odata.type", "@odata.id"}, ...}
       ]}
     Our handler verifies the `clientState` matches what we stored
     and enqueues an incremental sync.
  4. Mail subscriptions max out at ~3 days. Step 4's daemon renews
     every 2 days via PATCH.

Subscriptions are OPTIONAL: when `MICROSOFT_GRAPH_WEBHOOK_URL` is
empty, `subscribe_if_configured` is a no-op and the mailbox is
synced via Step 4's poll fallback. The webhook endpoint returns
503 in that case so misconfigured pushes can't sneak in.

`clientState` derivation: HMAC-SHA256 of the account id under the
shared signing key (`JWT_SECRET_KEY`). Per-subscription deterministic,
verifiable without an extra DB column, and rotates automatically if
the signing key rotates.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    JWT_SECRET_KEY,
    MICROSOFT_GRAPH_WEBHOOK_URL,
)
from src.app.core.email.microsoft.client import GraphClient, GraphHTTPError
from src.app.core.email.models import EmailAccount


logger = logging.getLogger(__name__)


# Graph caps mail subscriptions at 4230 minutes (~70 hours). Use 65h
# to leave headroom for clock skew on the renewal timer.
_INITIAL_EXPIRATION_HOURS = 65
_RENEWAL_EXPIRATION_HOURS = 65


def webhook_configured() -> bool:
    """True when this deploy has a public webhook URL set —
    callers branch on this to decide whether to call
    `subscriptions.create`."""
    return bool(MICROSOFT_GRAPH_WEBHOOK_URL)


def client_state_for(account_id) -> str:
    """Derive the `clientState` for an account's subscription —
    HMAC-SHA256(account_id) under JWT_SECRET_KEY. The first 32
    hex characters are sufficient (128 bits of entropy)."""
    key = (JWT_SECRET_KEY or "").encode("utf-8")
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured; cannot derive "
            "Graph subscription clientState."
        )
    mac = hmac.new(key, str(account_id).encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


async def subscribe_if_configured(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GraphClient] = None,
) -> Optional[dict]:
    """Register a Graph change-notification subscription for the
    account's mailbox if a webhook URL is configured. Returns the
    subscription payload Graph echoed back (the `id` we'll later
    PATCH to renew), or None if push is disabled in this deploy.

    Best-effort: a failure to register the subscription is logged
    and the connect flow proceeds — Step 4's 60-second poll keeps
    the mailbox in sync."""
    if not webhook_configured():
        return None
    gc = client or GraphClient(account=account, session=session)
    expiration = (
        datetime.now(timezone.utc)
        + timedelta(hours=_INITIAL_EXPIRATION_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    payload = {
        "changeType": "created,updated,deleted",
        "notificationUrl": MICROSOFT_GRAPH_WEBHOOK_URL,
        "resource": "/me/messages",
        "expirationDateTime": expiration,
        "clientState": client_state_for(account.id),
    }
    try:
        return await gc.create_subscription(payload=payload)
    except GraphHTTPError as exc:
        logger.warning(
            "Graph subscriptions.create failed for account=%s "
            "status=%s body=%s — falling back to poll-only sync",
            account.id,
            exc.status_code,
            exc.body,
        )
        return None


async def unsubscribe_quiet(
    account: EmailAccount,
    session: AsyncSession,
    *,
    subscription_id: Optional[str],
    client: Optional[GraphClient] = None,
) -> None:
    """Tear down an existing subscription. Idempotent: missing
    `subscription_id`, missing webhook URL, or a 404 from Graph
    is silently swallowed — disconnect must always succeed locally
    even if the remote teardown fails."""
    if not webhook_configured() or not subscription_id:
        return
    gc = client or GraphClient(account=account, session=session)
    try:
        await gc.delete_subscription(subscription_id)
    except (GraphHTTPError, HTTPException) as exc:
        logger.warning(
            "Graph subscriptions.delete failed for account=%s "
            "subscription=%s err=%s (ignored)",
            account.id,
            subscription_id,
            exc,
        )


async def renew_subscription(
    account: EmailAccount,
    session: AsyncSession,
    *,
    subscription_id: str,
    client: Optional[GraphClient] = None,
) -> Optional[str]:
    """Extend `expirationDateTime` by 65 hours. Returns the new
    expiration ISO string Graph echoed back, or None on failure
    (caller marks the subscription dead, schedules a re-subscribe
    on next sync)."""
    gc = client or GraphClient(account=account, session=session)
    new_iso = (
        datetime.now(timezone.utc)
        + timedelta(hours=_RENEWAL_EXPIRATION_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        body = await gc.renew_subscription(
            subscription_id, new_expiration_iso=new_iso
        )
        return str(body.get("expirationDateTime") or new_iso)
    except GraphHTTPError as exc:
        logger.warning(
            "Graph subscriptions.renew failed for account=%s "
            "subscription=%s status=%s",
            account.id,
            subscription_id,
            exc.status_code,
        )
        return None


# --- Webhook envelope handling -----------------------------------------


def decode_notification(envelope: dict) -> list[dict]:
    """Validate the inbound notification envelope shape and return
    the `value` array — every item is one change event.

    Graph batches events when several fire close together; the
    handler iterates the list and enqueues sync for each distinct
    subscriptionId."""
    if not isinstance(envelope, dict) or "value" not in envelope:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Graph notification envelope missing 'value'.",
        )
    items = envelope.get("value") or []
    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Graph notification 'value' is not a list.",
        )
    return items


def assert_client_state(notification: dict, *, expected: str) -> None:
    """Constant-time compare the inbound notification's clientState
    against the value we issued at subscription time. Mismatch =
    forged/spoofed notification."""
    inbound = str(notification.get("clientState") or "")
    if not hmac.compare_digest(inbound, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Graph notification clientState mismatch.",
        )


async def find_account_by_subscription_id(
    session: AsyncSession, subscription_id: str
) -> Optional[EmailAccount]:
    """Resolve an inbound notification's subscriptionId to the
    `email_accounts` row. We store Graph subscription ids in
    `email_accounts.sync_cursor` — same column reused for Gmail's
    historyId — but only when push is configured AND we successfully
    subscribed. The lookup bypasses the tenant filter (push has no
    tenant context yet) via raw SQL, mirroring the Gmail
    `find_account_by_email` and the integrations
    `get_by_webhook_secret` patterns.

    NOTE: we DO NOT mix subscription ids and delta-link URLs in the
    same column for v1. Step 4 will introduce a dedicated
    `email_accounts.subscription_id` column when it lands the
    renewal scheduler. For Step 3 push is rare in dev (Graph
    requires HTTPS + public webhook URL), so this lookup is exercised
    in production-only paths and the constraint is acceptable.
    """
    sql = text(
        """
        SELECT id, org_id, user_id, provider, external_account_id,
               email_address, display_name, access_token_enc,
               refresh_token_enc, token_expires_at, scopes_granted,
               sync_cursor, sync_state, last_sync_at, last_sync_error,
               daily_sent_count, daily_sent_reset_at, connected_at,
               disconnected_at, disconnected_by
        FROM email_accounts
        WHERE provider = 'microsoft'
          AND sync_cursor = :sub_id
          AND sync_state != 'disconnected'
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"sub_id": subscription_id})
    ).mappings().first()
    if row is None:
        return None
    from src.app.core.email.models import (
        EmailAccountProvider,
        EmailAccountSyncState,
    )

    return EmailAccount(
        id=row["id"],
        org_id=row["org_id"],
        user_id=row["user_id"],
        provider=EmailAccountProvider(row["provider"]),
        external_account_id=row["external_account_id"],
        email_address=row["email_address"],
        display_name=row["display_name"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes_granted=row["scopes_granted"] or [],
        sync_cursor=row["sync_cursor"],
        sync_state=EmailAccountSyncState(row["sync_state"]),
        last_sync_at=row["last_sync_at"],
        last_sync_error=row["last_sync_error"],
        daily_sent_count=row["daily_sent_count"],
        daily_sent_reset_at=row["daily_sent_reset_at"],
        connected_at=row["connected_at"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
    )


__all__ = [
    "assert_client_state",
    "client_state_for",
    "decode_notification",
    "find_account_by_subscription_id",
    "renew_subscription",
    "subscribe_if_configured",
    "unsubscribe_quiet",
    "webhook_configured",
]
