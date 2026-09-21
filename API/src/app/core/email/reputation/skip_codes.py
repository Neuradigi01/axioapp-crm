"""Skip-code enum + human-readable messages for the send-gate chain.

Every gate maps a failed pre-flight to one of these codes. Downstream
callers (campaign send loop, single-contact compose, AI reply engine)
log the code + move on — a distinct code per reason so support-debug
can point at "the wallet was empty" vs "the domain got shed" without
grepping through a generic 'send skipped' log line.
"""

from __future__ import annotations

from enum import Enum


class SendSkipCode(str, Enum):
    """Names locked; string values are stable so log-parsers key off
    the value not the enum member. New codes append; existing codes
    do not renumber."""

    REPUTATION_BLOCK = "SKIPPED_REPUTATION_BLOCK"
    SENDING_LIMIT = "SKIPPED_SENDING_LIMIT"
    WALLET_EMPTY = "SKIPPED_WALLET_EMPTY"
    RATE_LIMIT = "SKIPPED_RATE_LIMIT"


_HUMAN_MESSAGES: dict[SendSkipCode, str] = {
    SendSkipCode.REPUTATION_BLOCK: (
        "This org's reputation is currently blocked; sending resumes at "
        "the row's blocked_until timestamp."
    ),
    SendSkipCode.SENDING_LIMIT: (
        "This envelope has hit its warmup-stage daily cap. Waits for "
        "the daily reset at midnight UTC."
    ),
    SendSkipCode.WALLET_EMPTY: ("The org's send-credit wallet is empty. Top up before sending."),
    SendSkipCode.RATE_LIMIT: (
        "This envelope has hit its per-hour rate limit. Retry in a few minutes."
    ),
}


def human_message(code: SendSkipCode) -> str:
    """Return the operator-facing message for a skip code. Falls back
    to the raw enum value on an unknown code so a caller building an
    email preview doesn't crash on a mismatched enum."""
    return _HUMAN_MESSAGES.get(code, code.value)


__all__ = ["SendSkipCode", "human_message"]
