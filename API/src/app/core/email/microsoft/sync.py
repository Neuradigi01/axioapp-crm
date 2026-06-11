"""Microsoft Graph backfill + incremental sync primitives.

Strategy:
  - **Backfill** uses `/me/messages?$filter=receivedDateTime ge {iso}`
    to walk the last N days. Pages via `@odata.nextLink`. After the
    filter walk finishes, we seed a delta cursor by calling
    `/me/messages/delta` once and walking quickly to its `@odata.
    deltaLink` — that URL becomes `account.sync_cursor`.

  - **Incremental sync** hits the stored `deltaLink` URL directly.
    Graph returns either `@odata.nextLink` (more pages this round)
    or `@odata.deltaLink` (no more events; persist as next cursor).

Both functions match recipients (from + to + cc + bcc) against
`contacts.email` for the active tenant and return
`MatchedMessage(graph_message_id, headers, matched_contact_id)`
records — the caller (Step 4 / Step 5) persists them.

Neither function fetches the raw MIME — that's a separate call by
the consumer via `GraphClient.get_message_raw(...)`. The metadata
fetch path keeps backfill cheap on large mailboxes.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.models import Contact
from src.app.core.email.microsoft.client import GraphClient, GraphHTTPError
from src.app.core.email.models import EmailAccount


# Page size for filter walks. Graph max is 1000 but smaller pages
# play nicer with the per-tenant 10K/10min rate limit when many
# accounts sync concurrently. 50 matches the spec.
_PAGE_SIZE = 50
# Ceiling on a single backfill walk — protects against runaway
# pagination on a five-year-old mailbox. Step 4 resumes from the
# delta cursor if we hit this.
_BACKFILL_MESSAGE_CAP = 5_000

_SELECT_FIELDS = ",".join(
    [
        "id",
        "subject",
        "from",
        "toRecipients",
        "ccRecipients",
        "bccRecipients",
        "internetMessageId",
        "conversationId",
        "receivedDateTime",
        "sentDateTime",
    ]
)


@dataclass(frozen=True, slots=True)
class MatchedMessage:
    """One inbound or outbound message that matched a known contact.

    `raw_b64` is `None` from sync — these primitives only fetch
    metadata. The caller decides whether to pull the raw MIME via
    `GraphClient.get_message_raw(id)` and persist.
    """

    graph_message_id: str
    graph_conversation_id: Optional[str]
    headers: dict[str, str]
    matched_contact_id: uuid.UUID


@dataclass(slots=True)
class SyncResult:
    matched: list[MatchedMessage] = field(default_factory=list)
    scanned_count: int = 0
    new_cursor: Optional[str] = None
    truncated: bool = False
    delta_link_expired: bool = False


# --- Public entry points ------------------------------------------------


async def backfill(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GraphClient] = None,
    days: int = 30,
) -> SyncResult:
    """Filter-walk the last `days` of /me/messages, return matched
    rows. After the filter walk, seed a delta cursor for incremental
    sync to pick up from.
    """
    gc = client or GraphClient(account=account, session=session)
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_expr = f"receivedDateTime ge {cutoff}"

    result = SyncResult()
    next_link: Optional[str] = None

    # Phase 1: filter walk.
    while True:
        if next_link:
            envelope = await gc.get_absolute(next_link)
        else:
            envelope = await gc.list_messages(
                filter_expr=filter_expr,
                select=_SELECT_FIELDS,
                top=_PAGE_SIZE,
                order_by="receivedDateTime desc",
            )
        for msg in envelope.get("value") or []:
            if result.scanned_count >= _BACKFILL_MESSAGE_CAP:
                result.truncated = True
                break
            result.scanned_count += 1
            matched = await _match_one(msg, session)
            if matched is not None:
                result.matched.append(matched)
        if result.truncated:
            break
        next_link = envelope.get("@odata.nextLink")
        if not next_link:
            break

    # Phase 2: seed delta cursor.
    result.new_cursor = await _seed_delta_cursor(gc)
    return result


async def sync_incremental(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GraphClient] = None,
) -> SyncResult:
    """Walk the stored deltaLink chain and collect matched messages.

    On a 410 from Graph (delta token too old — mail subscriptions
    purge events at ~7 days), set `delta_link_expired=True` on the
    result. The caller (Step 4) handles this by triggering a full
    `backfill()` and using its `new_cursor`.
    """
    if not account.sync_cursor:
        raise RuntimeError(
            f"email_account {account.id} has no sync_cursor — "
            "run backfill() first to seed it."
        )
    gc = client or GraphClient(account=account, session=session)
    result = SyncResult()

    next_url: Optional[str] = account.sync_cursor
    last_delta_link: Optional[str] = None

    while next_url:
        try:
            envelope = await gc.get_absolute(next_url)
        except GraphHTTPError as exc:
            if exc.status_code == 410:
                result.delta_link_expired = True
                return result
            raise
        for msg in envelope.get("value") or []:
            result.scanned_count += 1
            # delta responses include `@removed` for deletes — skip
            # those for v1; Step 5 will add tombstone handling.
            if msg.get("@removed"):
                continue
            # In the delta stream, messages have an `id` even when
            # only metadata is included — same shape as filter walk.
            matched = await _match_one(msg, session)
            if matched is not None:
                result.matched.append(matched)
        delta_link = envelope.get("@odata.deltaLink")
        next_link = envelope.get("@odata.nextLink")
        if delta_link:
            last_delta_link = delta_link
            next_url = None
        else:
            next_url = next_link

    result.new_cursor = last_delta_link or account.sync_cursor
    return result


# --- Internals -----------------------------------------------------------


async def _seed_delta_cursor(gc: GraphClient) -> Optional[str]:
    """Walk `/me/messages/delta` quickly to obtain the current
    `@odata.deltaLink` — that's the "from this moment on" cursor.

    Pagination on the initial delta walk visits every message in
    the mailbox in the worst case; we cap at 50 pages (= 2,500
    messages with the default page size) to avoid runaway costs in
    a one-time seed. If we hit the cap without seeing a deltaLink,
    return None and the caller falls back to a full re-backfill on
    next sync."""
    next_url: Optional[str] = None
    pages = 0
    while pages < 50:
        if next_url:
            envelope = await gc.get_absolute(next_url)
        else:
            envelope = await gc.list_messages_delta(
                select="id", top=_PAGE_SIZE
            )
        delta_link = envelope.get("@odata.deltaLink")
        if delta_link:
            return delta_link
        next_url = envelope.get("@odata.nextLink")
        if not next_url:
            return None
        pages += 1
    return None


async def _match_one(
    detail: dict, session: AsyncSession
) -> Optional[MatchedMessage]:
    """Return a `MatchedMessage` if any participant in `detail`
    matches a known contact in the active tenant.

    Graph's recipient shape is `{emailAddress: {address: "...",
    name: "..."}}`. We flatten across from/to/cc/bcc into a single
    address list and do the same lower()-IN lookup pattern as the
    Gmail adapter.
    """
    addresses = _collect_addresses(detail)
    if not addresses:
        return None
    by_addr = await _lookup_contacts_by_email(session, addresses)
    if not by_addr:
        return None
    for addr in addresses:
        contact_id = by_addr.get(addr)
        if contact_id is not None:
            return MatchedMessage(
                graph_message_id=detail["id"],
                graph_conversation_id=detail.get("conversationId"),
                headers=_extract_headers(detail),
                matched_contact_id=contact_id,
            )
    return None


def _collect_addresses(detail: dict) -> list[str]:
    """Pull every participant address out of the Graph message
    metadata. Lowercased for the contacts.email comparison."""
    out: list[str] = []
    # `from` is a single { emailAddress: {address, name} } object.
    from_obj = (detail.get("from") or {}).get("emailAddress") or {}
    addr = from_obj.get("address")
    if addr:
        out.append(addr.strip().lower())
    # to/cc/bcc are arrays of the same shape.
    for key in ("toRecipients", "ccRecipients", "bccRecipients"):
        for recipient in detail.get(key) or []:
            ea = recipient.get("emailAddress") or {}
            a = ea.get("address")
            if a:
                out.append(a.strip().lower())
    return out


def _extract_headers(detail: dict) -> dict[str, str]:
    """Reconstruct the rfc-822-shaped header subset Step 5's
    threading helper expects, from Graph's normalised fields.
    Standardised lower-cased keys so callers don't care which
    provider produced them."""
    headers: dict[str, str] = {}
    subject = detail.get("subject")
    if subject is not None:
        headers["subject"] = str(subject)
    msg_id = detail.get("internetMessageId")
    if msg_id:
        headers["message-id"] = str(msg_id)
    from_obj = (detail.get("from") or {}).get("emailAddress") or {}
    if from_obj.get("address"):
        name = from_obj.get("name") or ""
        addr = from_obj["address"]
        headers["from"] = f'{name} <{addr}>' if name else addr
    headers["to"] = _format_recipient_list(detail.get("toRecipients"))
    cc = _format_recipient_list(detail.get("ccRecipients"))
    if cc:
        headers["cc"] = cc
    bcc = _format_recipient_list(detail.get("bccRecipients"))
    if bcc:
        headers["bcc"] = bcc
    sent_at = detail.get("sentDateTime") or detail.get("receivedDateTime")
    if sent_at:
        headers["date"] = str(sent_at)
    convo = detail.get("conversationId")
    if convo:
        # Graph's `conversationId` lets us thread without parsing
        # In-Reply-To/References. Stash it under a non-standard
        # header name so Step 5's threading helper can fall back to
        # it when present.
        headers["x-graph-conversation-id"] = str(convo)
    return headers


def _format_recipient_list(recipients) -> str:
    if not recipients:
        return ""
    parts: list[str] = []
    for r in recipients:
        ea = r.get("emailAddress") or {}
        addr = ea.get("address")
        if not addr:
            continue
        name = ea.get("name") or ""
        parts.append(f'{name} <{addr}>' if name else addr)
    return ", ".join(parts)


async def _lookup_contacts_by_email(
    session: AsyncSession, addresses: list[str]
) -> dict[str, uuid.UUID]:
    """Same contact-lookup logic as the Gmail adapter's
    `_lookup_contacts_by_email`. Returns
    `{lower(address): contact.id}` for every match."""
    deduped = sorted({a for a in addresses if a})
    if not deduped:
        return {}
    rows = (
        await session.execute(
            select(Contact.id, func.lower(Contact.email)).where(
                func.lower(Contact.email).in_(deduped)
            )
        )
    ).all()
    return {addr: cid for (cid, addr) in rows if addr}


__all__ = [
    "MatchedMessage",
    "SyncResult",
    "backfill",
    "sync_incremental",
]
