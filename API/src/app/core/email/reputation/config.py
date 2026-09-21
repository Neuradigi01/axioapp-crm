"""Config knobs for the reputation-warmup evaluators.

Every value is env-driven so the Owner can retune thresholds without
a code change. Defaults come from ``THRESHOLDS-LOCKED.md`` — complaint
thresholds are LOCKED (Gmail + Yahoo cite the same 0.1%/0.3%); bounce
thresholds are PROVISIONAL (SES-shaped, revisit after 30d live data).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "reputation.config: %s=%r is not an integer; using default %d",
            name,
            raw,
            default,
        )
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "reputation.config: %s=%r is not a float; using default %f",
            name,
            raw,
            default,
        )
        return default


def _stage_caps() -> list[int]:
    """Parse ``EMAIL_WARMUP_STAGE_CAPS`` (comma-separated ints).

    Default ladder: 50 / 200 / 1000 / 5000 / 25000 / <unlimited>. An
    empty tail entry means "no cap" — Track 4 § 6 model. We express
    "no cap" as ``0``; :func:`stage_cap` translates that to a large
    sentinel so the ``daily_sent < cap`` predicate keeps working.

    Malformed entries fall back to the default without failing the
    process — a typo in prod shouldn't wedge the send-gate.
    """
    raw = os.getenv("EMAIL_WARMUP_STAGE_CAPS", "").strip()
    if not raw:
        return [50, 200, 1000, 5000, 25000, 0]
    try:
        parts = [p.strip() for p in raw.split(",")]
        return [int(p) if p else 0 for p in parts]
    except ValueError:
        logger.warning(
            "reputation.config: EMAIL_WARMUP_STAGE_CAPS=%r malformed; using default", raw
        )
        return [50, 200, 1000, 5000, 25000, 0]


# Sentinel — a stage cap of 0 in the env list means "no cap"; internally
# we compare ``daily_sent_count < cap`` so we hoist it to a large number.
_UNCAPPED_SENTINEL = 10_000_000


def stage_cap(stage: int) -> int:
    """Cap for ``stage``, clamped to the ladder length. Stage past the
    top rung stays at the top rung (or uncapped if the top was 0)."""
    caps = _stage_caps()
    if stage < 0:
        stage = 0
    idx = min(stage, len(caps) - 1)
    raw = caps[idx]
    return _UNCAPPED_SENTINEL if raw <= 0 else raw


def earn_fraction() -> float:
    """Fraction of the current-stage cap a row must SEND (through
    events) before it's eligible to advance. Default 0.5 = 50%."""
    return _float("EMAIL_CAMPAIGN_WARMUP_EARN_FRACTION", 0.5)


def complaint_rate_threshold() -> float:
    """Complaint-rate hard cap. Default 0.003 (0.30%) — the auto-shed
    trigger per Gmail's ``support.google.com/mail/answer/81126``:
    "reaching 0.3% or higher" makes senders "ineligible for
    mitigation". Yahoo cites the same 0.3% floor."""
    return _float("EMAIL_COMPLAINT_RATE_THRESHOLD", 0.003)


def bounce_rate_threshold() -> float:
    """Bounce-rate hard cap. Default 0.05 (5.0%) — PROVISIONAL,
    SES-shaped (no ISP publishes a bounce cap). Revisit after 30d
    live data per THRESHOLDS-LOCKED.md."""
    return _float("EMAIL_BOUNCE_RATE_THRESHOLD", 0.05)


def event_floor() -> int:
    """Minimum delivered events in the 24h window before ratio
    thresholds fire. Below this floor, a single complaint on a
    small-volume org can't trip the shed cascade."""
    return _int("EMAIL_REPUTATION_MIN_EVENTS", 100)


def breach_cooldown_hours() -> int:
    """Duration of the ``blocked`` state after a threshold breach.
    Default 4h — matches Prativani spec."""
    return _int("EMAIL_BREACH_COOLDOWN_HOURS", 4)


# Warning-zone fraction: state = 'warned' when a ratio crosses this
# fraction of the shed threshold. Default 0.80 — the Owner sees an
# amber banner + notification before the shed actually fires so they
# can throttle sends before losing 4h of delivery.
def warning_zone_fraction() -> float:
    return _float("EMAIL_REPUTATION_WARNING_ZONE_FRACTION", 0.80)


__all__ = [
    "bounce_rate_threshold",
    "breach_cooldown_hours",
    "complaint_rate_threshold",
    "earn_fraction",
    "event_floor",
    "stage_cap",
    "warning_zone_fraction",
]
