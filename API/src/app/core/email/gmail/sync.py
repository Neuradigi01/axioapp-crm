"""Gmail backfill + incremental sync primitives.

`backfill(account, session, *, days=30)` walks every message in the
last N days, extracts From/To/Cc/Bcc, and matches them
case-insensitively against `contacts.email` for the active tenant.
Matched messages are returned to the caller as
`MatchedMessage(gmail_message_id, headers, matched_contact_id,
raw_b64url=None)` — the caller (Step 4's daemon → Step 5's
conversation adapter) fetches `format=raw` for the matched ones and
persists.

`sync_incremental(account, session)` uses Gmail's
`users.history.list?startHistoryId=…` to fetch only events since
the last cursor. Same matching pipeline.

Neither function persists anything to `messages` / `activities` /
`conversations` — that responsibility lives in Step 5's adapter.
Step 2 is just primitives.
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
from src.app.core.email.gmail.client import GmailClient, GmailHTTPError
from src.app.core.email.models import EmailAccount


# A page of messages can be up to 500 per Gmail's quota; we use 100
# pages to keep latency tolerable and let the daemon back off.
_PAGE_SIZE = 100
# Hard ceiling on a single backfill — protects against a mailbox
# with millions of inbound mails in the last 30 days. Step 4 can
# resume from `sync_cursor` if we hit this.
_BACKFILL_MESSAGE_CAP = 5_000


@dataclass(frozen=True, slots=True)
class MatchedMessage:
    """One inbound or outbound message that matched a known contact.

    `raw_b64url` is `None` from backfill / sync_incremental — these
    primitives only fetch `format=metadata` to keep the bytes cheap.
    The caller (Step 4 / Step 5) decides whether to fetch `raw` and
    persist; that's a separate cost.
    """

    gmail_message_id: str
    gmail_thread_id: str
    headers: dict[str, str]
    matched_contact_id: uuid.UUID
    raw_b64url: Optional[str] = None


@dataclass(slots=True)
class SyncResult:
    """Outcome of a backfill or incremental sync. `scanned_count` is
    the number of Gmail message ids walked (not the number of matched
    messages); `matched` is the subset that touched a known contact.
    `new_cursor` is the historyId to persist on the account row."""

    matched: list[MatchedMessage] = field(default_factory=list)
    scanned_count: int = 0
    new_cursor: Optional[str] = None
    truncated: bool = False


# --- Public entry points -------------------------------------------------


async def backfill(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GmailClient] = None,
    days: int = 30,
) -> SyncResult:
    """Walk the last `days` of the mailbox, return every message that
    matched a known contact. Updates no DB rows beyond contact
    lookups; the caller persists.

    Returns the first `historyId` we observed as `new_cursor` so the
    caller can store it on the account row for subsequent incremental
    syncs to pick up from."""
    gc = client or GmailClient(account=account, session=session)
    query = f"newer_than:{days}d"

    result = SyncResult()
    page_token: Optional[str] = None
    first_history_id: Optional[str] = None

    while True:
        envelope = await gc.list_messages(
            q=query, page_token=page_token, max_results=_PAGE_SIZE
        )
        messages = envelope.get("messages") or []
        if not messages and not page_token:
            break
        for msg_stub in messages:
            if result.scanned_count >= _BACKFILL_MESSAGE_CAP:
                result.truncated = True
                break
            result.scanned_count += 1
            msg_id = msg_stub["id"]
            try:
                detail = await gc.get_message(msg_id, format="metadata")
            except GmailHTTPError as exc:
                if exc.status_code == 404:
                    # Race: deleted between list and get. Skip.
                    continue
                raise
            if first_history_id is None:
                hist = detail.get("historyId")
                if hist:
                    first_history_id = str(hist)
            matched = await _match_one(detail, session)
            if matched is not None:
                result.matched.append(matched)
        if result.truncated:
            break
        page_token = envelope.get("nextPageToken")
        if not page_token:
            break

    result.new_cursor = first_history_id
    return result


async def sync_incremental(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GmailClient] = None,
) -> SyncResult:
    """Pull every messageAdded event since `account.sync_cursor`.
    Returns matched messages + the new cursor.

    On a 404 from history.list, the cursor is too old (Gmail's
    history retention is roughly 7 days; an idle mailbox past that
    cannot be incrementally caught up). The caller is expected to
    handle 404 by triggering a fresh `backfill()` and using its
    `new_cursor`.
    """
    if not account.sync_cursor:
        raise RuntimeError(
            f"email_account {account.id} has no sync_cursor — "
            "run backfill() first to seed it."
        )
    gc = client or GmailClient(account=account, session=session)
    result = SyncResult()
    page_token: Optional[str] = None
    last_history_id: str = account.sync_cursor

    while True:
        envelope = await gc.list_history(
            start_history_id=account.sync_cursor,
            page_token=page_token,
            history_types=["messageAdded"],
        )
        page_history_id = envelope.get("historyId")
        if page_history_id:
            last_history_id = str(page_history_id)
        events = envelope.get("history") or []
        for event in events:
            for added in event.get("messagesAdded") or []:
                stub = added.get("message") or {}
                msg_id = stub.get("id")
                if not msg_id:
                    continue
                result.scanned_count += 1
                try:
                    detail = await gc.get_message(
                        msg_id, format="metadata"
                    )
                except GmailHTTPError as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                matched = await _match_one(detail, session)
                if matched is not None:
                    result.matched.append(matched)
        page_token = envelope.get("nextPageToken")
        if not page_token:
            break

    result.new_cursor = last_history_id
    return result


# --- Internals -----------------------------------------------------------


_HEADERS_OF_INTEREST = {
    "from",
    "to",
    "cc",
    "bcc",
    "subject",
    "date",
    "message-id",
    "in-reply-to",
    "references",
}
# Standard `Name <local@host>` pattern. Captures everything inside
# the angle brackets; for bare-address tokens (no name), the regex
# also accepts the unbracketed form.
_ADDRESS_RE = re.compile(
    r"(?:\"?([^<>\",]*)\"?\s*<([^<>\s]+)>)|([^,\s<>]+@[^,\s<>]+)"
)


def _extract_headers(payload: dict) -> dict[str, str]:
    """Pull the subset of headers we use downstream. Lower-cased
    keys; original-case values."""
    headers_list = (payload.get("payload") or {}).get("headers") or []
    out: dict[str, str] = {}
    for h in headers_list:
        name = (h.get("name") or "").lower()
        if name in _HEADERS_OF_INTEREST:
            out[name] = h.get("value") or ""
    return out


def _extract_addresses(header_value: str) -> list[str]:
    """Pull every email address out of a header value. RFC-2822 lets
    headers carry comma-separated lists with optional display names
    (`"Asha" <asha@x.com>, bob@y.com`). Lowercases the addresses
    for the contacts.email comparison."""
    out: list[str] = []
    if not header_value:
        return out
    for match in _ADDRESS_RE.finditer(header_value):
        # match group 2 is the bracketed form; group 3 the bare form.
        addr = (match.group(2) or match.group(3) or "").strip().lower()
        if addr:
            out.append(addr)
    return out


def _collect_participants(headers: dict[str, str]) -> list[str]:
    """Every address that participated in the message — from + to +
    cc + bcc. Sender's own mailbox address ends up in here too; the
    caller is expected to exclude `account.email_address` if needed."""
    addrs: list[str] = []
    for key in ("from", "to", "cc", "bcc"):
        addrs.extend(_extract_addresses(headers.get(key, "")))
    return addrs


async def _match_one(
    detail: dict, session: AsyncSession
) -> Optional[MatchedMessage]:
    """Return a `MatchedMessage` if any participant in `detail` is a
    known contact in the active tenant, else None.

    The contact lookup happens via the ORM tenant filter — RLS keeps
    us inside the active org. Picks the contact_id from whichever
    address matched first; if multiple contacts share addresses, we
    pick the first (deterministic by lowercased address ordering).
    """
    headers = _extract_headers(detail)
    participants = _collect_participants(headers)
    if not participants:
        return None
    by_addr = await _lookup_contacts_by_email(session, participants)
    if not by_addr:
        return None
    # Pick the contact for the first address (in original order) that
    # had a match. Stable, deterministic.
    for addr in participants:
        contact_id = by_addr.get(addr)
        if contact_id is not None:
            return MatchedMessage(
                gmail_message_id=detail["id"],
                gmail_thread_id=detail.get("threadId") or detail["id"],
                headers=headers,
                matched_contact_id=contact_id,
            )
    return None


async def _lookup_contacts_by_email(
    session: AsyncSession, addresses: list[str]
) -> dict[str, uuid.UUID]:
    """Resolve a batch of lowercased email addresses to contact ids
    in the active tenant. Returns `{lower(address): contact.id}` for
    every match; addresses without a contact are absent from the map.
    """
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
