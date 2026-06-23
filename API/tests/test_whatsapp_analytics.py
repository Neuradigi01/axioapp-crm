"""whatsapp-platform-upgrade Step 20 — analytics service boundary tests.

Covers the pure-Python helpers that don't touch the DB: range
resolution, granularity validation, percentile calculation, the
duration→bucket label mapper. Integration coverage (the SQL paths
themselves) is exercised via the smoke flow once the dashboard
lands, mirroring the precedent set by `test_assignment_engine.py`.

Cases:
  1. ``_resolve_range`` accepts 7d/30d/90d and rejects junk.
  2. ``_resolve_range`` returns a tz-aware UTC `(start, end)` tuple
     with the right delta.
  3. ``_resolve_granularity`` rejects unknown values.
  4. ``_resolve_granularity`` rejects hour+90d.
  5. ``_percentile`` returns None on empty.
  6. ``_percentile`` returns the only element on a 1-sample list.
  7. ``_percentile`` matches numpy-style linear interpolation on a
     known 5-sample set.
  8. ``_percentile`` handles a 1-element vs many-element sample
     consistently.
  9. ``_label_for_seconds`` walks every bucket boundary correctly.
 10. ``_label_for_seconds`` returns "> 24 hr" for the catch-all.
 11. Distribution bucket list covers exactly the expected labels.
"""
from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from src.app.core.reporting.whatsapp_analytics import (
    _DISTRIBUTION_BUCKETS,
    _label_for_seconds,
    _percentile,
    _resolve_granularity,
    _resolve_range,
)


class TestResolveRange:
    @pytest.mark.parametrize(
        "key,expected_days",
        [("7d", 7), ("30d", 30), ("90d", 90)],
    )
    def test_supported_keys(self, key, expected_days):
        start, end = _resolve_range(key)
        # Allow a small clock drift between the two `now()` calls in
        # the helper; we only assert the day count is correct.
        delta = end - start
        assert abs(delta - timedelta(days=expected_days)) < timedelta(seconds=2)
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert start.utcoffset() == timezone.utc.utcoffset(None)

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            _resolve_range("1y")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _resolve_range("")


class TestResolveGranularity:
    def test_day_accepted_for_every_range(self):
        for r in ("7d", "30d", "90d"):
            assert _resolve_granularity("day", r) == "day"

    def test_hour_accepted_for_short_ranges(self):
        assert _resolve_granularity("hour", "7d") == "hour"
        assert _resolve_granularity("hour", "30d") == "hour"

    def test_hour_rejected_for_90d(self):
        with pytest.raises(ValueError):
            _resolve_granularity("hour", "90d")

    def test_unknown_value(self):
        with pytest.raises(ValueError):
            _resolve_granularity("month", "30d")


class TestPercentile:
    def test_empty(self):
        assert _percentile([], 0.5) is None

    def test_single(self):
        assert _percentile([42.0], 0.5) == 42.0
        # Even at edges, single-sample stays the single value.
        assert _percentile([42.0], 0.0) == 42.0
        assert _percentile([42.0], 1.0) == 42.0

    def test_known_dataset(self):
        # 5 samples → linear-interp percentiles.
        # numpy.percentile([10,20,30,40,50], [50,95]) → [30, 48]
        samples = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(samples, 0.5) == pytest.approx(30.0)
        assert _percentile(samples, 0.95) == pytest.approx(48.0)

    def test_unsorted_input_handled(self):
        # The helper sorts internally; result must be stable.
        assert _percentile([50.0, 10.0, 30.0, 40.0, 20.0], 0.5) == pytest.approx(
            30.0
        )

    def test_edges(self):
        samples = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(samples, 0.0) == 10.0
        assert _percentile(samples, 1.0) == 50.0


class TestLabelForSeconds:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "< 1 min"),
            (30, "< 1 min"),
            (59, "< 1 min"),
            (60, "1–5 min"),
            (299, "1–5 min"),
            (300, "5–15 min"),
            (899, "5–15 min"),
            (900, "15–60 min"),
            (3599, "15–60 min"),
            (3600, "1–4 hr"),
            (14399, "1–4 hr"),
            (14400, "4–24 hr"),
            (86399, "4–24 hr"),
            (86400, "> 24 hr"),
            (172800, "> 24 hr"),
        ],
    )
    def test_bucket_boundaries(self, seconds, expected):
        assert _label_for_seconds(seconds) == expected

    def test_bucket_list_shape(self):
        # 6 finite buckets + 1 catch-all "> 24 hr".
        assert len(_DISTRIBUTION_BUCKETS) == 7
        # Catch-all sentinel is exactly -1.
        assert _DISTRIBUTION_BUCKETS[-1][1] == -1
        # Boundaries are strictly increasing.
        finite_upper_bounds = [u for _, u in _DISTRIBUTION_BUCKETS if u != -1]
        assert finite_upper_bounds == sorted(finite_upper_bounds)
        assert len(set(finite_upper_bounds)) == len(finite_upper_bounds)
