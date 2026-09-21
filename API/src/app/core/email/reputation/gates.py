"""Send-gate chain for the outbound email path.

Four gates in a defined order (cheapest-fail-first):

  1. :func:`check_reputation` — reads the reputation row's
     ``reputation_state`` / ``blocked_until``. No side-effects — pure
     read. If the row is ``blocked`` and the cooldown hasn't elapsed,
     raises :class:`SkippedReputationBlock`.

  2. :func:`check_ceiling` — reads the same row's ``daily_sent_count``
     against the current warmup-stage cap from :mod:`.config`. Also
     pure read. If ``daily_sent_count >= cap``, raises
     :class:`SkippedSendingLimit`.

  3. :func:`check_wallet` — spec-optional. Documented no-op while the
     credits system isn't wired in (Track 4 § dependencies). Returns
     a :class:`WalletDebit` sentinel the caller can pass to
     :func:`refund_wallet` on dispatch failure. When credits DO exist,
     this call debits; refunding on dispatch failure is essential.

  4. :func:`check_rate_limit` — sliding-window Redis rate check per
     envelope. Threshold from env — default 1000/h for ``own_domain``,
     100/h for ``platform_from``. Raises :class:`SkippedRateLimit` when
     the caller is over the cap.

Exceptions live in :mod:`.exceptions`; skip-code enum in :mod:`.
skip_codes`. All raise-based control flow lets the caller do a
single ``try/except SendGateSkipped as exc: log(exc.code)``.

``run_send_gate`` orchestrates the four in order. The refactor in
:func:`send_email` calls this at the top; the individual functions
are also exported so future adapters (SMS gateway, WhatsApp) can
reuse the shape without re-inventing the ordering.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation import config, data_access
from src.app.core.email.reputation.exceptions import (
    SkippedRateLimit,
    SkippedReputationBlock,
    SkippedSendingLimit,
)
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
)
from src.app.shared.rate_limit_shared import rate_hit

logger = logging.getLogger(__name__)


class WalletDebit(NamedTuple):
    """Handle returned by :func:`check_wallet`. Pass to
    :func:`refund_wallet` on dispatch failure. ``amount == 0`` means
    the wallet subsystem wasn't consulted (no-op path)."""

    org_id: uuid.UUID
    amount: int


# --- Gate 1: reputation ----------------------------------------------------


async def check_reputation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> None:
    """Raise :class:`SkippedReputationBlock` if the (org, envelope,
    domain) row is currently blocked. Missing row = no block (row is
    materialised on the first event; a brand-new envelope is by
    definition ok)."""
    row = await data_access.get_row(
        session,
        org_id=org_id,
        envelope_type=envelope_type,
        domain_id=domain_id,
    )
    if row is None:
        return
    if row.reputation_state != REPUTATION_STATE_BLOCKED:
        return
    now = datetime.now(UTC)
    if row.blocked_until is not None and row.blocked_until <= now:
        # The hourly sweeper hasn't flipped it back yet, but the
        # cooldown has elapsed. Let the send through — the sweeper's
        # next tick will clean up state.
        return
    raise SkippedReputationBlock(
        f"reputation blocked until {row.blocked_until.isoformat() if row.blocked_until else '?'}"
    )


# --- Gate 2: warmup-stage ceiling ------------------------------------------


async def check_ceiling(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> None:
    """Raise :class:`SkippedSendingLimit` if the row has sent up to its
    warmup-stage cap for the current daily window.

    A NULL / never-created row implies 0 sends → the check passes.
    First-time-send materialises the row on the events-webhook path
    (Step 3), so the ``daily_sent_count`` will only be non-zero after
    at least one event has landed.
    """
    row = await data_access.get_row(
        session,
        org_id=org_id,
        envelope_type=envelope_type,
        domain_id=domain_id,
    )
    if row is None:
        return
    cap = config.stage_cap(row.warmup_stage)
    if row.daily_sent_count >= cap:
        raise SkippedSendingLimit(
            f"daily_sent_count={row.daily_sent_count} cap={cap} "
            f"stage={row.warmup_stage} envelope={envelope_type}"
        )


# --- Gate 3: wallet debit --------------------------------------------------


def _wallet_enabled() -> bool:
    """Return True when the credits system should be consulted. Default
    False (no billing surface for credits shipped yet); a future
    billing track flips ``EMAIL_SEND_WALLET_ENABLED=true``."""
    return os.getenv("EMAIL_SEND_WALLET_ENABLED", "false").strip().lower() == "true"


async def check_wallet(
    session: AsyncSession,  # noqa: ARG001 — reserved for future debit call
    *,
    org_id: uuid.UUID,
) -> WalletDebit:
    """Debit one send-credit from the org's wallet. Returns a
    :class:`WalletDebit` handle for :func:`refund_wallet`.

    No-op today (spec § dependencies: billing track hasn't shipped
    credits). Returns ``WalletDebit(org_id, 0)`` so callers don't need
    a wallet-enabled branch.

    When wallet is enabled and empty: raises
    :class:`SkippedWalletEmpty`. The billing track will fill this in.
    """
    if not _wallet_enabled():
        return WalletDebit(org_id=org_id, amount=0)
    # Placeholder — the real debit call belongs to core.billing when
    # send-credits ship. For now, wallet_enabled=false is the shipped
    # path; enabling without an implementation would surface the
    # NotImplementedError so a mis-flip in prod fails LOUD.
    raise NotImplementedError(
        "EMAIL_SEND_WALLET_ENABLED=true but core.billing send-credits "
        "haven't shipped yet. Flip the flag back or wire the debit path."
    )


async def refund_wallet(
    session: AsyncSession,  # noqa: ARG001
    *,
    debit: WalletDebit,
) -> None:
    """Roll back a wallet debit (dispatch failed after we charged).
    No-op when ``amount == 0`` — matches the shipped-today path.
    """
    if debit.amount == 0:
        return
    raise NotImplementedError("wallet refund path awaits core.billing send-credits shipping")


# --- Gate 4: rate limit ----------------------------------------------------


def _rate_limit_per_hour(envelope_type: str) -> int:
    """Per-envelope hourly cap. Defaults from Track 4 § 5 —
    provisional pending Mailgun's response-header numbers. Values
    live in env so ops can tune under load."""
    if envelope_type == ENVELOPE_TYPE_OWN_DOMAIN:
        try:
            return int(os.getenv("EMAIL_RATE_LIMIT_OWN_DOMAIN_PER_HOUR", "1000"))
        except ValueError:
            return 1000
    # platform_from (default + safest fallback).
    try:
        return int(os.getenv("EMAIL_RATE_LIMIT_PLATFORM_FROM_PER_HOUR", "100"))
    except ValueError:
        return 100


async def check_rate_limit(
    *,
    org_id: uuid.UUID,
    envelope_type: str,
) -> None:
    """Sliding-window Redis rate check. Raises
    :class:`SkippedRateLimit` when the caller has hit the per-hour
    cap for this envelope.

    Rate is keyed on ``(org_id, envelope_type)`` — a spammy platform
    tenant doesn't shed another tenant's rate budget. Redis-down =
    fail-open (rate_hit returns True on the in-proc fallback path,
    which is what we want for availability).
    """
    key = f"send:{org_id}:{envelope_type}"
    limit = _rate_limit_per_hour(envelope_type)
    admitted = await rate_hit(key, limit=limit, window_seconds=3600)
    if not admitted:
        raise SkippedRateLimit(f"hourly cap={limit} exceeded for envelope={envelope_type}")


# --- Orchestrator ----------------------------------------------------------


def _gates_enabled() -> bool:
    """Kill-switch — set ``EMAIL_REPUTATION_GATES_ENABLED=false`` in an
    incident to bypass the whole chain and restore pre-Step-5 send
    behaviour without a rollback."""
    return os.getenv("EMAIL_REPUTATION_GATES_ENABLED", "true").strip().lower() != "false"


async def run_send_gate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> WalletDebit:
    """Run the four gates in order. Returns the wallet-debit handle on
    success. Raises the first :class:`SendGateSkipped` subclass that
    fires; the caller catches and logs the code.

    ``envelope_type`` is one of ``platform_from`` / ``own_domain``.
    Adapter callers that don't yet track ``domain_id`` should pass
    None for ``platform_from`` (the row lookup filters accordingly).
    """
    if not _gates_enabled():
        logger.info("reputation.gates: EMAIL_REPUTATION_GATES_ENABLED=false — skipping gates")
        return WalletDebit(org_id=org_id, amount=0)

    if envelope_type not in (ENVELOPE_TYPE_PLATFORM_FROM, ENVELOPE_TYPE_OWN_DOMAIN):
        # Send paths that don't fit the reputation model (OAuth
        # personal mailbox etc) skip the chain — reputation tracks
        # only mailgun-mediated envelopes.
        return WalletDebit(org_id=org_id, amount=0)

    started = time.monotonic()
    await check_reputation(session, org_id=org_id, envelope_type=envelope_type, domain_id=domain_id)
    await check_ceiling(session, org_id=org_id, envelope_type=envelope_type, domain_id=domain_id)
    debit = await check_wallet(session, org_id=org_id)
    try:
        await check_rate_limit(org_id=org_id, envelope_type=envelope_type)
    except Exception:
        # Refund the debit — check_wallet succeeded but the rate gate
        # closed. Symmetric with the dispatch-failure refund the
        # adapter does after this returns.
        await refund_wallet(session, debit=debit)
        raise

    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms > 200:
        # A gate chain slower than 200ms points at a Redis hot-path or
        # a DB-lock issue — worth an ops log line.
        logger.info(
            "reputation.gates: slow gate chain org=%s envelope=%s took %.1fms",
            org_id,
            envelope_type,
            elapsed_ms,
        )
    return debit


__all__ = [
    "WalletDebit",
    "check_ceiling",
    "check_rate_limit",
    "check_reputation",
    "check_wallet",
    "refund_wallet",
    "run_send_gate",
]
