"""Filter-rule precedence resolver + per-sender rate cap.

Consumed by :mod:`src.app.core.email.mailgun.tasks` in Step 4. Kept
in its own module so tests can exercise the rule engine + rate limiter
without the whole webhook plumbing.

**Precedence** (locked in the track README):

  * ``allow`` beats ``block`` at any specificity — a matching allow
    rule short-circuits the block gate.
  * Within the same rule_type, specificity wins: ``email_address``
    beats ``contact_flag`` beats ``email_domain``.

**Rate cap** — per-sender-address, per-org, hourly. Backed by Redis
time-bucketed counter (matches the mailgun-webhook rate-shed pattern).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Iterable

from src.app.core.email.quarantine.models import (
    MATCH_KIND_CONTACT_FLAG,
    MATCH_KIND_EMAIL_ADDRESS,
    MATCH_KIND_EMAIL_DOMAIN,
    RULE_TYPE_ALLOW,
    RULE_TYPE_BLOCK,
    EmailFilterRule,
)

logger = logging.getLogger(__name__)

# Specificity ranking — higher wins within a rule_type.
_KIND_SPECIFICITY = {
    MATCH_KIND_EMAIL_ADDRESS: 3,
    MATCH_KIND_CONTACT_FLAG: 2,
    MATCH_KIND_EMAIL_DOMAIN: 1,
}


@dataclass(frozen=True)
class RuleDecision:
    """Result of :func:`decide_filter_action`."""

    action: str  # "allow" | "block" | "pass"
    rule_id: uuid.UUID | None = None
    matched_kind: str | None = None


def decide_filter_action(
    *,
    from_address: str,
    contact_flags: Iterable[str] = (),
    rules: Iterable[EmailFilterRule],
) -> RuleDecision:
    """Given the set of effective rules for an (org, endpoint), decide
    whether to allow-through, block, or pass.

    ``pass`` means no rule fired — the caller's other gates (SPF/DKIM,
    rate cap, etc.) still run.
    """
    from_lower = from_address.lower().strip()
    domain = from_lower.rpartition("@")[2]
    flags_lower = {f.lower().strip() for f in contact_flags}

    best_allow: tuple[int, EmailFilterRule] | None = None
    best_block: tuple[int, EmailFilterRule] | None = None

    for rule in rules:
        if not _rule_matches(rule, from_lower=from_lower, domain=domain, flags=flags_lower):
            continue
        specificity = _KIND_SPECIFICITY[rule.match_kind]
        if rule.rule_type == RULE_TYPE_ALLOW:
            if best_allow is None or specificity > best_allow[0]:
                best_allow = (specificity, rule)
        elif rule.rule_type == RULE_TYPE_BLOCK:
            if best_block is None or specificity > best_block[0]:
                best_block = (specificity, rule)

    # Allow beats block regardless of specificity.
    if best_allow is not None:
        return RuleDecision(
            action="allow",
            rule_id=best_allow[1].id,
            matched_kind=best_allow[1].match_kind,
        )
    if best_block is not None:
        return RuleDecision(
            action="block",
            rule_id=best_block[1].id,
            matched_kind=best_block[1].match_kind,
        )
    return RuleDecision(action="pass")


def _rule_matches(
    rule: EmailFilterRule,
    *,
    from_lower: str,
    domain: str,
    flags: set[str],
) -> bool:
    value = (rule.match_value or "").lower().strip()
    if rule.match_kind == MATCH_KIND_EMAIL_ADDRESS:
        return value == from_lower
    if rule.match_kind == MATCH_KIND_EMAIL_DOMAIN:
        return value == domain
    if rule.match_kind == MATCH_KIND_CONTACT_FLAG:
        return value in flags
    return False


# ---------------------------------------------------------------------------
# Per-sender hourly rate cap
# ---------------------------------------------------------------------------


_DEFAULT_SENDER_HOURLY_CAP = 20


def sender_hourly_cap() -> int:
    """Read from env each call so ops can tune without restarts."""
    try:
        return max(
            1,
            int(
                os.getenv(
                    "EMAIL_INBOUND_SENDER_HOURLY_CAP", str(_DEFAULT_SENDER_HOURLY_CAP)
                )
            ),
        )
    except ValueError:
        return _DEFAULT_SENDER_HOURLY_CAP


def _bucket_key(org_id: uuid.UUID, from_address: str) -> str:
    hour = int(time.time() // 3600)
    return f"mgw:sender:{org_id}:{from_address.lower().strip()}:{hour}"


@dataclass(frozen=True)
class RateCapDecision:
    """Result of :func:`check_sender_rate_cap`."""

    action: str  # "pass" | "quarantine" | "drop_silent"
    counter_value: int


async def check_sender_rate_cap(
    *,
    org_id: uuid.UUID,
    from_address: str,
) -> RateCapDecision:
    """Redis time-bucketed counter, hourly. Fail-open on Redis outage."""
    from src.app.shared.rate_limit_shared import get_redis

    cap = sender_hourly_cap()
    try:
        redis = await get_redis()
        key = _bucket_key(org_id, from_address)
        # INCR then set TTL if fresh key (nx). TTL 65 min covers the
        # rollover window without leaving stale keys past the hour.
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 65 * 60)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "quarantine.gates: redis outage — rate cap fail-open: %s", exc
        )
        return RateCapDecision(action="pass", counter_value=0)

    if count <= cap:
        return RateCapDecision(action="pass", counter_value=count)
    if count == cap + 1:
        # First over-cap message quarantines; every subsequent one
        # drops silently to avoid quarantine spam from a noisy sender.
        return RateCapDecision(action="quarantine", counter_value=count)
    return RateCapDecision(action="drop_silent", counter_value=count)


__all__ = [
    "RateCapDecision",
    "RuleDecision",
    "check_sender_rate_cap",
    "decide_filter_action",
    "sender_hourly_cap",
]
