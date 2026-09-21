"""Send-gate exception hierarchy.

Every skip-code has a paired exception. The gate chain raises the
first exception that fires; the caller catches ``SendGateSkipped``
(the parent) to handle any skip uniformly, or the concrete class
for reason-specific logic (e.g., refund the wallet debit only on
``SkippedRateLimit`` since ``SkippedWalletEmpty`` never charged).
"""

from __future__ import annotations

from src.app.core.email.reputation.skip_codes import SendSkipCode


class SendGateSkipped(Exception):
    """Base — every send-gate rejection is an instance of this. Carry
    the enum code so caller logs / API responses can serialise it
    without introspecting the exception type."""

    code: SendSkipCode

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code.value)


class SkippedReputationBlock(SendGateSkipped):
    code = SendSkipCode.REPUTATION_BLOCK


class SkippedSendingLimit(SendGateSkipped):
    code = SendSkipCode.SENDING_LIMIT


class SkippedWalletEmpty(SendGateSkipped):
    code = SendSkipCode.WALLET_EMPTY


class SkippedRateLimit(SendGateSkipped):
    code = SendSkipCode.RATE_LIMIT


__all__ = [
    "SendGateSkipped",
    "SkippedRateLimit",
    "SkippedReputationBlock",
    "SkippedSendingLimit",
    "SkippedWalletEmpty",
]
