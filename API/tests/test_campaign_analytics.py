"""whatsapp-platform-upgrade Step 21 — campaign analytics + cost
estimator boundary tests.

Pure-Python coverage of the failure-reason classifier, the cost-rate
table + override path, the cost line-item math, and the category
normaliser. SQL aggregation paths (funnel / failures / cost /
quality timeline / AI metrics) are exercised via the live smoke
flow once seed campaigns land — same precedent as Step 18's
assignment-engine + Step 20's whatsapp-analytics tests.

Cases:
  1. Failure classifier picks `rate_limited` on "rate limit reached".
  2. Failure classifier picks `invalid_number` on Meta's
     "Recipient not on WhatsApp".
  3. Failure classifier picks `opted_out` on "User has not opted in".
  4. Failure classifier picks `template_paused` on paused / rejected.
  5. Failure classifier picks `quality_restricted` on "messaging limit
     reached".
  6. Failure classifier falls through to `other` for empty / unknown.
  7. `normalise_category` maps Meta UPPERCASE values to lowercase set.
  8. `normalise_category` maps unknown to `utility` (median catch-all).
  9. `normalise_category` returns `service` on falsy input.
 10. `get_rates` returns the IN default table.
 11. `get_rates` falls back to IN for unknown regions.
 12. `WHATSAPP_COST_RATES_OVERRIDE` overlays one category without
     wiping the others.
 13. Bad JSON in the env override is ignored without raising.
 14. `estimate` totals match Σ(count × rate) across categories.
 15. `estimate` folds an unknown category key into `utility`.
 16. `estimate` reports the right currency for AE / US.
"""

from __future__ import annotations

import json

import pytest

from src.app.core.reporting import cost_estimator
from src.app.core.reporting.campaign_analytics import (
    FAILURE_REASONS,
    _classify_failure,
)


class TestFailureClassifier:
    @pytest.mark.parametrize(
        "error,expected",
        [
            ("Rate limit reached", "rate_limited"),
            ("Throttling, slow down", "rate_limited"),
            ("Recipient not on WhatsApp", "invalid_number"),
            ("Invalid phone number", "invalid_number"),
            ("Non-existing user", "invalid_number"),
            ("User has not opted in for messages", "opted_out"),
            ("opted out", "opted_out"),
            ("Template paused", "template_paused"),
            ("Template rejected by review", "template_paused"),
            ("Quality dropped below threshold", "quality_restricted"),
            ("Messaging limit reached", "quality_restricted"),
            ("Phone blocked by user", "quality_restricted"),
            ("Tier downgrade", "quality_restricted"),
            ("Some random new Meta error", "other"),
            ("", "other"),
            (None, "other"),
        ],
    )
    def test_classification(self, error, expected):
        assert _classify_failure(error) == expected

    def test_all_taxonomy_keys_unique(self):
        assert len(set(FAILURE_REASONS)) == len(FAILURE_REASONS)


class TestNormaliseCategory:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MARKETING", "marketing"),
            ("Marketing", "marketing"),
            ("marketing", "marketing"),
            ("UTILITY", "utility"),
            ("AUTHENTICATION", "authentication"),
            ("SERVICE", "service"),
            ("TRANSACTIONAL", "marketing"),  # legacy alias
            ("ALERT_UPDATE", "utility"),
            ("OTP", "utility"),  # unknown → utility
            ("RANDOM_NEW_CATEGORY", "utility"),
        ],
    )
    def test_known_mappings(self, raw, expected):
        assert cost_estimator.normalise_category(raw) == expected

    def test_falsy_returns_service(self):
        assert cost_estimator.normalise_category(None) == "service"
        assert cost_estimator.normalise_category("") == "service"


class TestRateLookup:
    def test_defaults_for_india(self):
        rates = cost_estimator.get_rates("IN")
        assert rates["marketing"] > 0
        assert rates["service"] == 0.0
        assert set(rates.keys()) >= set(cost_estimator.CATEGORIES)

    def test_unknown_region_falls_back_to_in(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_COST_RATES_OVERRIDE", raising=False)
        default_in = cost_estimator.get_rates("IN")
        assert cost_estimator.get_rates("ZZ") == default_in

    def test_currency_lookup(self):
        assert cost_estimator.currency_for("IN") == "INR"
        assert cost_estimator.currency_for("AE") == "AED"
        assert cost_estimator.currency_for("US") == "USD"
        assert cost_estimator.currency_for("ZZ") == "INR"  # fallback


class TestRateOverride:
    def test_override_layered_on_top(self, monkeypatch):
        monkeypatch.setenv(
            "WHATSAPP_COST_RATES_OVERRIDE",
            json.dumps({"IN": {"marketing": 1.23}}),
        )
        rates = cost_estimator.get_rates("IN")
        assert rates["marketing"] == 1.23
        # Other categories stay at their defaults.
        assert rates["service"] == 0.0
        assert rates["utility"] > 0

    def test_bad_json_ignored(self, monkeypatch, caplog):
        monkeypatch.setenv("WHATSAPP_COST_RATES_OVERRIDE", "{not json}")
        rates = cost_estimator.get_rates("IN")
        # Defaults still present despite the malformed override.
        assert "marketing" in rates
        assert rates["service"] == 0.0

    def test_unknown_category_in_override_silently_dropped(self, monkeypatch):
        monkeypatch.setenv(
            "WHATSAPP_COST_RATES_OVERRIDE",
            json.dumps({"IN": {"marketing": 1.0, "frobnicate": 9.99}}),
        )
        rates = cost_estimator.get_rates("IN")
        assert rates["marketing"] == 1.0
        assert "frobnicate" not in rates


class TestEstimate:
    def test_totals_match_sum_of_lines(self):
        report = cost_estimator.estimate(
            region="IN",
            counts={
                "marketing": 100,
                "utility": 50,
                "authentication": 20,
                "service": 1000,
            },
        )
        recomputed = sum(line.total for line in report.lines)
        assert report.total == pytest.approx(recomputed)

    def test_unknown_category_folded_into_utility(self):
        report = cost_estimator.estimate(
            region="IN",
            counts={"marketing": 10, "bogus": 5},
        )
        # Pull the utility line, which absorbed the bogus 5.
        util_line = next(line for line in report.lines if line.category == "utility")
        assert util_line.count == 5

    def test_currency_per_region(self):
        in_report = cost_estimator.estimate(region="IN", counts={"marketing": 1})
        ae_report = cost_estimator.estimate(region="AE", counts={"marketing": 1})
        us_report = cost_estimator.estimate(region="US", counts={"marketing": 1})
        assert in_report.currency == "INR"
        assert ae_report.currency == "AED"
        assert us_report.currency == "USD"

    def test_service_line_is_zero_cost(self):
        report = cost_estimator.estimate(region="IN", counts={"service": 9999})
        service_line = next(line for line in report.lines if line.category == "service")
        assert service_line.total == 0.0
        assert report.total == 0.0

    def test_empty_counts_produce_zero_total(self):
        report = cost_estimator.estimate(region="IN", counts={})
        assert report.total == 0.0
        # All four category lines still present so the UI table stays
        # consistent across windows with no traffic.
        assert {line.category for line in report.lines} == set(cost_estimator.CATEGORIES)

    def test_is_estimate_flag(self):
        report = cost_estimator.estimate(region="IN", counts={"marketing": 1})
        assert report.is_estimate is True
