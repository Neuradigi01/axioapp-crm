"""WhatsApp 24-hour session window helper
(whatsapp-platform-upgrade Step 15).

Single entry point — :func:`compute_session_state` — that turns the
conversation's `last_customer_message_at` timestamp into the read
shape the frontend banner + composer key off:

    {
        "in_session": bool,
        "expires_at": datetime | None,
        "hours_remaining": float,
        "last_customer_message_at": datetime | None,
    }

Boundary rule (per Meta's docs): the window is "less than 24 hours
since the customer's last message". Exactly 24h → out of session.
NULL `last_customer_message_at` (customer never replied) → out of
session.

The function is pure — no DB hits, no clocks beyond `datetime.now`
— so the router/service layer can call it cheaply on every detail
fetch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

SESSION_WINDOW = timedelta(hours=24)


def compute_session_state(
    last_customer_message_at: datetime | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the session-state dict for the given last-customer-
    message timestamp.

    `now` is exposed only for tests — production callers should let
    it default to ``datetime.now(timezone.utc)`` so the window math
    is consistent across requests."""
    current = now or datetime.now(UTC)

    if last_customer_message_at is None:
        return {
            "in_session": False,
            "expires_at": None,
            "hours_remaining": 0.0,
            "last_customer_message_at": None,
        }

    expires_at = last_customer_message_at + SESSION_WINDOW
    delta = expires_at - current
    in_session = delta > timedelta(0)
    # Round to one decimal place — the frontend renders "4h 12m" by
    # converting back, so we keep the wire value compact + precise
    # enough that the minute display lines up.
    hours_remaining = max(delta.total_seconds() / 3600.0, 0.0)

    return {
        "in_session": in_session,
        "expires_at": expires_at,
        "hours_remaining": round(hours_remaining, 4),
        "last_customer_message_at": last_customer_message_at,
    }


__all__ = ["SESSION_WINDOW", "compute_session_state"]
