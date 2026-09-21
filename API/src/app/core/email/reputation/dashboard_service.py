"""Read-only aggregation for the reputation dashboard.

Kept in its own module (not :mod:`.service`) because :mod:`.service`
already owns the event-ingest write path — mixing a read-only
aggregator into the same file would break the transaction-boundary
discipline (``service.py`` is the only layer that commits; this
module intentionally never touches the session mutably).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.reputation import config, counters
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_OK,
    OrganizationEmailReputation,
)
from src.app.core.email.reputation.schemas import EnvelopeReputationOut
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)

logger = logging.getLogger(__name__)


def _compute_stage_progress(
    daily_sent: int,
    cap: int,
) -> float:
    """Return progress as a 0-100 float. Clamps to 100 when the row
    has punched over the cap (unlikely but harmless)."""
    if cap <= 0:
        return 100.0
    return min(100.0, (daily_sent / cap) * 100.0)


async def _read_24h(
    org_id: uuid.UUID,
    envelope_type: str,
    domain_id: uuid.UUID | None,
) -> dict[str, int]:
    """Fetch the four rolling counters in parallel-ish (each is a
    single MGET; not worth an asyncio.gather for four calls)."""
    out: dict[str, int] = {}
    for event in ("delivered", "bounced", "complained", "unsubscribed"):
        out[event] = await counters.sum_last_24h(
            org_id=org_id,
            envelope=envelope_type,
            domain_id=domain_id,
            event=event,  # type: ignore[arg-type]
        )
    return out


def _row_to_out(
    row: OrganizationEmailReputation | None,
    *,
    envelope_type: str,
    domain_id: uuid.UUID | None,
    domain_string: str | None,
    counts: dict[str, int],
) -> EnvelopeReputationOut:
    """Materialise the response from a row (may be None for pristine
    envelopes) + the pre-fetched 24h counts."""
    warmup_stage = row.warmup_stage if row else 0
    daily_sent = row.daily_sent_count if row else 0
    reputation_state = row.reputation_state if row else REPUTATION_STATE_OK
    blocked_until = row.blocked_until if row else None
    stage_cap = config.stage_cap(warmup_stage)
    next_stage_cap = config.stage_cap(warmup_stage + 1)
    delivered = counts.get("delivered", 0)
    complaint_rate = counts.get("complained", 0) / delivered if delivered else 0.0
    bounce_rate = counts.get("bounced", 0) / delivered if delivered else 0.0
    return EnvelopeReputationOut(
        envelope_type=envelope_type,
        domain_id=domain_id,
        domain_string=domain_string,
        warmup_stage=warmup_stage,
        stage_cap=stage_cap,
        next_stage_cap=next_stage_cap,
        stage_progress_pct=_compute_stage_progress(daily_sent, stage_cap),
        daily_sent=daily_sent,
        daily_cap=stage_cap,
        delivered_24h=delivered,
        bounced_24h=counts.get("bounced", 0),
        complained_24h=counts.get("complained", 0),
        unsubscribed_24h=counts.get("unsubscribed", 0),
        complaint_rate=complaint_rate,
        bounce_rate=bounce_rate,
        reputation_state=reputation_state,
        blocked_until=blocked_until,
    )


async def list_reputation_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[EnvelopeReputationOut]:
    """Build the dashboard payload for one org.

    Order:
      1. ``platform_from`` — always one row, even when no events yet
         (synthetic pristine card).
      2. Each verified ``own_domain`` — one row per verified domain,
         with the domain string surfaced for display.
    """
    # Load reputation rows first so we can index by (envelope, domain).
    rep_rows = list(
        (
            await session.execute(
                select(OrganizationEmailReputation).where(
                    OrganizationEmailReputation.org_id == org_id
                )
            )
        )
        .scalars()
        .all()
    )
    rep_by_key: dict[tuple[str, uuid.UUID | None], OrganizationEmailReputation] = {}
    for r in rep_rows:
        rep_by_key[(r.envelope_type, r.domain_id)] = r

    out: list[EnvelopeReputationOut] = []

    # Row 1 — platform_from. Synthetic when there's no row yet.
    pf_row = rep_by_key.get((ENVELOPE_TYPE_PLATFORM_FROM, None))
    pf_counts = await _read_24h(org_id, ENVELOPE_TYPE_PLATFORM_FROM, None)
    out.append(
        _row_to_out(
            pf_row,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
            domain_string=None,
            counts=pf_counts,
        )
    )

    # Rows 2..N — one per verified own-domain.
    domains = list(
        (
            await session.execute(
                select(OrganizationEmailDomain)
                .where(OrganizationEmailDomain.org_id == org_id)
                .where(OrganizationEmailDomain.verification_status == VERIFICATION_STATUS_VERIFIED)
            )
        )
        .scalars()
        .all()
    )
    for d in domains:
        row = rep_by_key.get((ENVELOPE_TYPE_OWN_DOMAIN, d.id))
        counts = await _read_24h(org_id, ENVELOPE_TYPE_OWN_DOMAIN, d.id)
        out.append(
            _row_to_out(
                row,
                envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
                domain_id=d.id,
                domain_string=d.domain,
                counts=counts,
            )
        )
    return out


__all__ = ["list_reputation_for_org"]
