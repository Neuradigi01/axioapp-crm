"""WhatsApp cost estimator
(whatsapp-platform-upgrade Step 21).

Meta charges by **conversation category** (Marketing / Utility /
Authentication / Service) at a per-country rate. We don't have the
Meta invoice API, so this is a best-effort *estimate*:

  * For every outbound row we determine the category from the
    template metadata (campaign sends) or fall back to ``service``
    (free within the 24-hour customer-initiated window).
  * Multiply the per-category count by the org's region rate.
  * Sum across categories for the displayed total.

Tagged "Estimate" in the UI so nobody mistakes it for the actual
Meta invoice.

Rate table
----------

Hardcoded for India / UAE / US (the three real-world deploys we
have). The env var ``WHATSAPP_COST_RATES_OVERRIDE`` accepts JSON of
shape ``{"IN": {"marketing": 0.85, ...}, ...}`` and overlays
whatever it ships. Single source of truth so the cost widget and
campaign cost-line both pull from one table.

Rates as of 2026-06-24 in **org-local currency** (INR / AED / USD).
These are public Meta pricing — see
https://developers.facebook.com/docs/whatsapp/pricing — and may
drift; the override env var lets ops correct them without a deploy.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Meta's conversation categories. Lowercase string to keep parity
# with the wire format used by the templates API. "service" is the
# free customer-initiated bucket — Meta charges nothing within the
# 24-hour session window, so it stays in the table at zero.
CATEGORIES: tuple[str, ...] = (
    "marketing",
    "utility",
    "authentication",
    "service",
)


Region = str  # ISO 3166-1 alpha-2 — "IN" / "AE" / "US"


@dataclass(frozen=True, slots=True)
class CostLine:
    category: str
    count: int
    rate: float
    currency: str
    total: float


@dataclass(frozen=True, slots=True)
class CostEstimate:
    region: Region
    currency: str
    lines: list[CostLine]
    total: float
    is_estimate: bool = True


# Public list-rate snapshot — same per-category structure for each
# region; the rate scale differs.
_DEFAULT_RATES: dict[Region, dict[str, float]] = {
    "IN": {
        "marketing": 0.8846,
        "utility": 0.1150,
        "authentication": 0.1278,
        "service": 0.0,
    },
    "AE": {
        "marketing": 0.0340,
        "utility": 0.0125,
        "authentication": 0.0136,
        "service": 0.0,
    },
    "US": {
        "marketing": 0.0250,
        "utility": 0.0150,
        "authentication": 0.0135,
        "service": 0.0,
    },
}


_CURRENCY: dict[Region, str] = {
    "IN": "INR",
    "AE": "AED",
    "US": "USD",
}


_DEFAULT_REGION: Region = "IN"


def _load_overrides() -> dict[Region, dict[str, float]]:
    """Read ``WHATSAPP_COST_RATES_OVERRIDE`` JSON if set.

    Bad JSON or missing categories are logged + ignored — the
    cost-estimator must never fail the dashboard, only the
    accuracy of the displayed numbers."""
    raw = os.getenv("WHATSAPP_COST_RATES_OVERRIDE")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("invalid WHATSAPP_COST_RATES_OVERRIDE JSON")
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[Region, dict[str, float]] = {}
    for region, table in parsed.items():
        if not isinstance(table, dict):
            continue
        cleaned: dict[str, float] = {}
        for cat, val in table.items():
            cat = cat.lower()
            if cat not in CATEGORIES:
                continue
            try:
                cleaned[cat] = float(val)
            except (TypeError, ValueError):
                continue
        if cleaned:
            out[region.upper()] = cleaned
    return out


def get_rates(region: Region) -> dict[str, float]:
    """Effective per-category rate table for the region.

    Layers env-side overrides on top of the hardcoded defaults so
    the override only needs to ship the categories it wants to
    change. Unknown regions fall back to ``IN``."""
    region = (region or _DEFAULT_REGION).upper()
    base = dict(_DEFAULT_RATES.get(region, _DEFAULT_RATES[_DEFAULT_REGION]))
    overrides = _load_overrides().get(region, {})
    base.update(overrides)
    # Ensure every category is present so callers can `.get(cat)` without
    # a KeyError; a missing override leaves the default in place.
    for cat in CATEGORIES:
        base.setdefault(cat, 0.0)
    return base


def currency_for(region: Region) -> str:
    return _CURRENCY.get((region or _DEFAULT_REGION).upper(), "INR")


def estimate(
    *,
    region: Region,
    counts: dict[str, int],
) -> CostEstimate:
    """Build a ``CostEstimate`` from per-category counts.

    Unknown category keys are folded into the ``utility`` line so
    the total still represents the outbound volume — better to
    over-estimate than to silently drop messages from the bill.
    """
    rates = get_rates(region)
    currency = currency_for(region)
    cleaned: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    for cat, n in counts.items():
        key = cat.lower() if isinstance(cat, str) else "utility"
        if key not in cleaned:
            key = "utility"
        cleaned[key] += int(n or 0)

    lines: list[CostLine] = []
    total = 0.0
    for cat in CATEGORIES:
        count = cleaned.get(cat, 0)
        rate = rates.get(cat, 0.0)
        line_total = round(count * rate, 4)
        lines.append(
            CostLine(
                category=cat,
                count=count,
                rate=rate,
                currency=currency,
                total=line_total,
            )
        )
        total += line_total

    return CostEstimate(
        region=region.upper() if region else _DEFAULT_REGION,
        currency=currency,
        lines=lines,
        total=round(total, 4),
    )


def normalise_category(raw: str | None) -> str:
    """Map a Meta template ``category`` field onto our lower-case
    set. Unknown → "utility" (the median-cost catch-all). Used by
    the campaign-analytics service when classifying outbound rows."""
    if not raw:
        return "service"
    lowered = str(raw).lower()
    if lowered in CATEGORIES:
        return lowered
    # Meta historically uses uppercase enum names; the templates table
    # stores whatever the API returned. Map the common ones.
    if lowered in ("marketing", "transactional", "promotion"):
        return "marketing"
    if lowered == "authentication":
        return "authentication"
    if lowered in ("utility", "alert_update", "account_update", "issue_resolution"):
        return "utility"
    return "utility"


__all__ = [
    "CATEGORIES",
    "CostEstimate",
    "CostLine",
    "Region",
    "currency_for",
    "estimate",
    "get_rates",
    "normalise_category",
]
