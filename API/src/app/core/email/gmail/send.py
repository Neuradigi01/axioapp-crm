"""Outbound send via Gmail — wraps the user's own connected mailbox.

`send(account, session, raw_mime, *, thread_id=None)` is the single
entry point. The MIME bytes come in pre-built (the caller — Step 5's
conversations email adapter — assembles them with Subject, From, To,
threading headers, body parts, and later the open pixel + rewritten
links from Step 8).

Daily cap enforcement happens here, atomically against the
`email_accounts.daily_sent_count` row:

  - Soft cap (default 200) → send proceeds + a `DailyCapWarning` is
    annotated on the response payload so the compose UI can surface
    a banner.
  - Hard cap (default 500) → send raises `DailyCapExceeded(429)`;
    the daemon defers the send to tomorrow (relevant in Step 7's
    sequence scheduler).

The midnight UTC reset is handled by Step 4's daemon, not here —
this code only checks the current counter and increments it.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.gmail.client import GmailClient, GmailHTTPError
from src.app.core.email.models import EmailAccount

# Soft cap = warn the rep; hard cap = block. Env-overridable so a
# customer's whitelisted Workspace can lift the ceiling.
DEFAULT_SOFT_CAP = int(os.getenv("EMAIL_DAILY_SOFT_CAP", "200"))
DEFAULT_HARD_CAP = int(os.getenv("EMAIL_DAILY_HARD_CAP", "500"))


class DailyCapExceeded(HTTPException):
    """Raised when the per-account hard cap has been hit. 429 so the
    Step 5 adapter + Step 7 sequence scheduler can branch on a clear
    HTTP-level signal."""

    def __init__(self, *, sent: int, cap: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(f"Daily send cap reached for this account ({sent}/{cap}). Try again tomorrow."),
        )


@dataclass(slots=True)
class SendResult:
    """Outcome of a successful Gmail send."""

    gmail_message_id: str
    gmail_thread_id: str | None
    daily_sent_after: int
    near_soft_cap: bool


async def send(
    account: EmailAccount,
    session: AsyncSession,
    *,
    raw_mime: bytes,
    thread_id: str | None = None,
    client: GmailClient | None = None,
    soft_cap: int = DEFAULT_SOFT_CAP,
    hard_cap: int = DEFAULT_HARD_CAP,
) -> SendResult:
    """Post `raw_mime` to Gmail as a sent message. Returns the
    `(message_id, thread_id)` Gmail allocated + the new daily-sent
    count + whether the send pushed us to within 10% of the soft cap.

    The daily counter is incremented BEFORE the HTTP call, with a
    rollback if Gmail rejects, so two concurrent sends can never
    double-spend the cap. Gmail's `messages.send` is fast enough that
    the lock-then-call pattern is acceptable for v1.
    """
    _ensure_under_hard_cap(account, hard_cap)

    # Build the request payload first — fail fast on a malformed MIME
    # before consuming a cap slot.
    raw_b64url = base64.urlsafe_b64encode(raw_mime).decode("ascii").rstrip("=")

    # Optimistic increment. If Gmail rejects, we decrement.
    account.daily_sent_count = (account.daily_sent_count or 0) + 1
    await session.commit()

    gc = client or GmailClient(account=account, session=session)
    try:
        response = await gc.send_message(raw_b64url=raw_b64url, thread_id=thread_id)
    except (GmailHTTPError, HTTPException):
        # Roll the counter back on any send failure — the user can
        # retry without burning a slot. We re-raise the exception
        # untouched so the caller sees the upstream reason.
        account.daily_sent_count = max(0, account.daily_sent_count - 1)
        await session.commit()
        raise

    return SendResult(
        gmail_message_id=response["id"],
        gmail_thread_id=response.get("threadId"),
        daily_sent_after=account.daily_sent_count,
        near_soft_cap=account.daily_sent_count >= int(soft_cap * 0.9)
        and account.daily_sent_count < hard_cap,
    )


def _ensure_under_hard_cap(account: EmailAccount, hard_cap: int) -> None:
    """Reject the send up-front when the row is already at or above
    the hard cap. The midnight reset is Step 4's daemon — this just
    reads the current value."""
    if (account.daily_sent_count or 0) >= hard_cap:
        raise DailyCapExceeded(sent=account.daily_sent_count, cap=hard_cap)


__all__ = [
    "DEFAULT_HARD_CAP",
    "DEFAULT_SOFT_CAP",
    "DailyCapExceeded",
    "SendResult",
    "send",
]
