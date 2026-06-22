"""whatsapp-platform-upgrade Step 10 — per-template performance tests.

Pure-Python boundary tests around the failure-classification mapper
and the rate-computation helper. End-to-end aggregation is covered
by integration tests against a live DB (out of scope here — the
query is straightforward joins; the harder parts are the bucket
labels + zero-denominator handling).

Cases:
  1. Rate of 0/0 returns 0.0 (no NaN, no divide-by-zero).
  2. Rate caps at 100 even when numerator races ahead of denominator.
  3. Failure classifier maps "rate" → rate_limited bucket.
  4. Failure classifier maps "Recipient blocked" → opted_out bucket.
  5. Failure classifier maps "phone number is invalid" → invalid_number.
  6. Failure classifier maps "template was paused" → template_paused.
  7. Empty / None error text returns ("other", "Other").
"""
from __future__ import annotations

from src.app.core.integrations.whatsapp.templates_analytics import (
    _classify_failure,
    _rate,
)


class TestRateHelper:
    def test_zero_denominator_returns_zero(self):
        assert _rate(0, 0) == 0.0

    def test_zero_denominator_with_positive_numerator_returns_zero(self):
        # Defensive: when sent=0 but delivered=5 (impossible in
        # production but happens in tests with stub rows), we treat it
        # as 0% so the UI doesn't show "Infinity %".
        assert _rate(5, 0) == 0.0

    def test_normal_rate_rounds_to_one_decimal(self):
        assert _rate(47, 50) == 94.0

    def test_caps_at_one_hundred_percent(self):
        # `delivered` racing ahead of `sent` (an in-flight webhook
        # arriving before our own dispatch persists) shouldn't surface
        # as a > 100% rate. Cap defensively.
        assert _rate(60, 50) == 100.0


class TestFailureClassifier:
    def test_rate_limited_substring(self):
        bucket, label = _classify_failure(
            "Rate limit hit on Meta's side, retry in 30 minutes."
        )
        assert bucket == "rate_limited"
        assert label == "Rate limited"

    def test_throttle_substring_also_rate_limited(self):
        bucket, _ = _classify_failure(
            "Sending throttled — wait for capacity."
        )
        assert bucket == "rate_limited"

    def test_blocked_maps_to_opted_out(self):
        bucket, label = _classify_failure(
            "Recipient has blocked the business."
        )
        assert bucket == "opted_out"
        assert label == "Recipient opted out"

    def test_invalid_number(self):
        bucket, label = _classify_failure(
            "The phone number is invalid for messaging."
        )
        assert bucket == "invalid_number"
        assert label == "Invalid number"

    def test_template_paused(self):
        bucket, label = _classify_failure(
            "Template was paused due to poor quality rating."
        )
        assert bucket == "template_paused"
        assert label == "Template paused"

    def test_disabled_also_template_paused(self):
        bucket, _ = _classify_failure(
            "Template has been disabled by Meta."
        )
        assert bucket == "template_paused"

    def test_unknown_falls_back_to_other(self):
        bucket, label = _classify_failure(
            "Some never-before-seen Meta error string."
        )
        assert bucket == "other"
        assert label == "Other"

    def test_empty_string_is_other(self):
        bucket, label = _classify_failure("")
        assert bucket == "other"
        assert label == "Other"

    def test_none_is_other(self):
        bucket, label = _classify_failure(None)
        assert bucket == "other"
        assert label == "Other"
