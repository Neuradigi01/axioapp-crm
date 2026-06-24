"""whatsapp-platform-upgrade Step 29 — campaign A/B boundary tests.

Pure-Python coverage of:
  * Deterministic variant assignment (`_assign_ab_variant`).
  * Split-ratio distribution across a 1k-sample population.
  * Schema validation of A/B campaigns (variant pair / metric /
    distinct templates / non-A/B passes unchanged).
  * `_pick_winner` decision rules + tie-break.

Live-DB paths (audience guard, dispatch loop persistence, Celery
scheduling) are exercised by the smoke flow — same precedent as
prior steps.

Cases:
  1.  `_assign_ab_variant` is deterministic on the same (cid, contact).
  2.  Split ratio 50 produces roughly a 50/50 distribution across 1k
      samples (allow 10% slack).
  3.  Split ratio 80 leans 80% toward A (10% slack).
  4.  Split ratio 0 sends every contact to B.
  5.  Split ratio 100 sends every contact to A.
  6.  `CampaignCreate` rejects A/B with one variant id missing.
  7.  `CampaignCreate` rejects A/B with identical variant ids.
  8.  `CampaignCreate` rejects A/B without a winner_metric.
  9.  `CampaignCreate` accepts a valid A/B payload.
 10.  Non-A/B `CampaignCreate` still requires exactly one template source.
 11.  `_pick_winner` favors higher rate.
 12.  `_pick_winner` returns None when both variants had 0 samples.
 13.  `_pick_winner` falls back to the other variant when one had 0 samples.
 14.  `_pick_winner` tie-breaks to A on equal rates.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.campaigns.ab_decider import (
    VariantMetrics,
    _pick_winner,
)
from src.app.core.campaigns.schemas import CampaignCreate
from src.app.core.campaigns.service import _assign_ab_variant


def _ab_payload(**overrides) -> dict:
    base = {
        "name": "T",
        "channel": "whatsapp",
        "is_ab_test": True,
        "variant_a_template_id": str(uuid.uuid4()),
        "variant_b_template_id": str(uuid.uuid4()),
        "winner_metric": "reply_rate",
        "split_ratio": 50,
        "winner_holdback_hours": 24,
    }
    base.update(overrides)
    return base


class TestVariantAssignment:
    def test_deterministic(self):
        cid = uuid.uuid4()
        contact = uuid.uuid4()
        first = _assign_ab_variant(
            campaign_id=cid, contact_id=contact, split_ratio=50
        )
        second = _assign_ab_variant(
            campaign_id=cid, contact_id=contact, split_ratio=50
        )
        assert first == second

    def test_distribution_50_50(self):
        cid = uuid.uuid4()
        contacts = [uuid.uuid4() for _ in range(1000)]
        assignments = [
            _assign_ab_variant(
                campaign_id=cid, contact_id=c, split_ratio=50
            )
            for c in contacts
        ]
        a_count = assignments.count("A")
        # Allow generous 10% slack — SHA-256 isn't perfectly uniform
        # over 100 buckets at this sample size, but should be close.
        assert 400 <= a_count <= 600, a_count

    def test_distribution_80_20(self):
        cid = uuid.uuid4()
        contacts = [uuid.uuid4() for _ in range(1000)]
        assignments = [
            _assign_ab_variant(
                campaign_id=cid, contact_id=c, split_ratio=80
            )
            for c in contacts
        ]
        a_count = assignments.count("A")
        assert 700 <= a_count <= 900, a_count

    def test_split_zero_all_b(self):
        cid = uuid.uuid4()
        contacts = [uuid.uuid4() for _ in range(50)]
        for c in contacts:
            assert (
                _assign_ab_variant(
                    campaign_id=cid, contact_id=c, split_ratio=0
                )
                == "B"
            )

    def test_split_hundred_all_a(self):
        cid = uuid.uuid4()
        contacts = [uuid.uuid4() for _ in range(50)]
        for c in contacts:
            assert (
                _assign_ab_variant(
                    campaign_id=cid, contact_id=c, split_ratio=100
                )
                == "A"
            )


class TestCampaignCreateValidation:
    def test_missing_variant_b_rejected(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(
                _ab_payload(variant_b_template_id=None)
            )

    def test_missing_variant_a_rejected(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(
                _ab_payload(variant_a_template_id=None)
            )

    def test_identical_variants_rejected(self):
        shared = str(uuid.uuid4())
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(
                _ab_payload(
                    variant_a_template_id=shared,
                    variant_b_template_id=shared,
                )
            )

    def test_missing_metric_rejected(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(_ab_payload(winner_metric=None))

    def test_split_ratio_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(_ab_payload(split_ratio=150))
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(_ab_payload(split_ratio=-5))

    def test_valid_ab_passes(self):
        payload = CampaignCreate.model_validate(_ab_payload())
        assert payload.is_ab_test is True
        assert payload.winner_metric == "reply_rate"

    def test_non_ab_still_requires_template_source(self):
        # The legacy "exactly one of template / template_id" check
        # must still fire for non-A/B campaigns.
        with pytest.raises(ValidationError):
            CampaignCreate.model_validate(
                {"name": "T", "channel": "whatsapp"}
            )


class TestPickWinner:
    def _metrics(
        self, variant: str, samples: int, numerator: int
    ) -> VariantMetrics:
        rate = (numerator / samples) if samples else 0.0
        return VariantMetrics(
            variant=variant,
            samples=samples,
            numerator=numerator,
            rate=rate,
        )

    def test_higher_rate_wins(self):
        a = self._metrics("A", 100, 30)  # 0.30
        b = self._metrics("B", 100, 50)  # 0.50
        winner, _ = _pick_winner(a, b)
        assert winner == "B"

    def test_zero_samples_both_no_winner(self):
        a = self._metrics("A", 0, 0)
        b = self._metrics("B", 0, 0)
        winner, reason = _pick_winner(a, b)
        assert winner is None
        assert "no samples" in reason.lower()

    def test_zero_samples_one_falls_back_to_other(self):
        a = self._metrics("A", 0, 0)
        b = self._metrics("B", 100, 1)
        winner, _ = _pick_winner(a, b)
        assert winner == "B"

    def test_tiebreak_to_a(self):
        a = self._metrics("A", 100, 30)
        b = self._metrics("B", 100, 30)
        winner, reason = _pick_winner(a, b)
        assert winner == "A"
        assert "tie" in reason.lower()
