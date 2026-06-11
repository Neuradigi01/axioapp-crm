"""Outbound send via Microsoft Graph — `POST /me/sendMail`.

Mirrors `core.email.gmail.send`: daily cap enforcement, optimistic
counter increment with rollback on send failure.

Caveat: Graph's `sendMail` endpoint returns **202 No Content** with
no message id. Unlike Gmail, Graph does NOT echo back a server-side
message id. The outbound MIME's `Message-ID` header (set by Step 5's
adapter at MIME assembly time) becomes the correlation key — it's
the same id Outlook will return on subsequent fetches, and the same
id the recipient's reply will reference in its `In-Reply-To`.

`SendResult.provider_message_id` is therefore `None` for this
adapter. Step 5 will read the Message-ID header from the raw MIME
bytes when it persists the outbound `messages` row.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.microsoft.client import GraphClient, GraphHTTPError
from src.app.core.email.models import EmailAccount


# Same defaults as the Gmail adapter. Step 5 may surface per-org
# overrides; the env-var fallback below covers global tuning.
DEFAULT_SOFT_CAP = int(os.getenv("EMAIL_DAILY_SOFT_CAP", "200"))
DEFAULT_HARD_CAP = int(os.getenv("EMAIL_DAILY_HARD_CAP", "500"))


class DailyCapExceeded(HTTPException):
    """Raised when the per-account hard cap is hit. 429 so the
    sequence scheduler can branch on a clear signal."""

    def __init__(self, *, sent: int, cap: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily send cap reached for this account "
                f"({sent}/{cap}). Try again tomorrow."
            ),
        )


@dataclass(slots=True)
class SendResult:
    """Outcome of a successful Graph send. `provider_message_id`
    is None — Graph's sendMail doesn't return one (see module
    docstring)."""

    provider_message_id: Optional[str]
    daily_sent_after: int
    near_soft_cap: bool


async def send(
    account: EmailAccount,
    session: AsyncSession,
    *,
    raw_mime: bytes,
    client: Optional[GraphClient] = None,
    soft_cap: int = DEFAULT_SOFT_CAP,
    hard_cap: int = DEFAULT_HARD_CAP,
) -> SendResult:
    """Post `raw_mime` to Graph via sendMail. Returns the daily-
    sent counter + soft-cap flag. Increments the counter BEFORE the
    HTTP call and rolls back on Graph failure."""
    _ensure_under_hard_cap(account, hard_cap)

    raw_b64 = base64.b64encode(raw_mime).decode("ascii")

    account.daily_sent_count = (account.daily_sent_count or 0) + 1
    await session.commit()

    gc = client or GraphClient(account=account, session=session)
    try:
        await gc.send_raw(raw_b64=raw_b64)
    except (GraphHTTPError, HTTPException):
        account.daily_sent_count = max(0, account.daily_sent_count - 1)
        await session.commit()
        raise

    return SendResult(
        provider_message_id=None,
        daily_sent_after=account.daily_sent_count,
        near_soft_cap=account.daily_sent_count >= int(soft_cap * 0.9)
        and account.daily_sent_count < hard_cap,
    )


def _ensure_under_hard_cap(account: EmailAccount, hard_cap: int) -> None:
    if (account.daily_sent_count or 0) >= hard_cap:
        raise DailyCapExceeded(
            sent=account.daily_sent_count, cap=hard_cap
        )


__all__ = [
    "DEFAULT_HARD_CAP",
    "DEFAULT_SOFT_CAP",
    "DailyCapExceeded",
    "SendResult",
    "send",
]
