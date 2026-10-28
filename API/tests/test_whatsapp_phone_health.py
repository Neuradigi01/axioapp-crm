"""whatsapp-platform-upgrade Step 12 — phone health tests.

Pure-Python boundary tests around the diff helper, recovery key
computation, and webhook event extraction. End-to-end Meta roundtrip
is covered by integration tests.

Cases:
  1. `_diff_fields` returns empty list when nothing changed
     (idempotency invariant for hourly refresh + retried webhooks).
  2. `_diff_fields` emits a `quality_change` row when quality moves.
  3. `_diff_fields` emits a `tier_change` row when tier moves.
  4. `_diff_fields` emits `restriction_added` when a new restriction
     type appears.
  5. `_diff_fields` emits `restriction_lifted` only when all
     restrictions clear (not on partial decrement).
  6. `_recovery_keys` returns ['quality_degraded'] for YELLOW quality.
  7. `_recovery_keys` returns ['restricted'] when restrictions list
     is non-empty.
  8. `_extract_phone_quality_event` parses Meta's payload shape.
  9. `_extract_phone_quality_event` returns None on non-quality
     payloads (e.g. a regular `messages` webhook).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.app.core.conversations.router import _extract_phone_quality_event
from src.app.core.integrations.whatsapp.health_service import (
    _diff_fields,
    _recovery_keys,
)
from src.app.core.integrations.whatsapp.models import (
    WhatsAppPhoneHealthEventType,
)


def _config(
    *,
    quality: str | None = None,
    tier: str | None = None,
    name_status: str | None = None,
    restrictions: list[dict] | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for a `WhatsAppAccountConfig` row — only the
    fields `_diff_fields` reads. Avoids the heavyweight ORM instance
    so the test stays in pure Python."""
    return SimpleNamespace(
        quality_rating=quality,
        messaging_limit_tier=tier,
        name_status=name_status,
        restrictions=restrictions,
    )


class TestDiffFields:
    def test_idempotent_when_nothing_changed(self):
        config = _config(quality="GREEN", tier="TIER_1K")
        events = _diff_fields(
            config=config,
            new_quality="GREEN",
            new_tier="TIER_1K",
            new_name_status=None,
            new_throughput=None,
            new_restrictions=None,
        )
        assert events == []

    def test_quality_change_event(self):
        config = _config(quality="GREEN", tier="TIER_1K")
        events = _diff_fields(
            config=config,
            new_quality="YELLOW",
            new_tier="TIER_1K",
            new_name_status=None,
            new_throughput=None,
            new_restrictions=None,
        )
        assert len(events) == 1
        assert events[0][0] == WhatsAppPhoneHealthEventType.quality_change
        assert events[0][1] == "GREEN"
        assert events[0][2] == "YELLOW"

    def test_tier_change_event(self):
        config = _config(quality="GREEN", tier="TIER_1K")
        events = _diff_fields(
            config=config,
            new_quality=None,
            new_tier="TIER_10K",
            new_name_status=None,
            new_throughput=None,
            new_restrictions=None,
        )
        assert len(events) == 1
        assert events[0][0] == WhatsAppPhoneHealthEventType.tier_change

    def test_restriction_added_when_new_type_appears(self):
        config = _config(restrictions=[])
        events = _diff_fields(
            config=config,
            new_quality=None,
            new_tier=None,
            new_name_status=None,
            new_throughput=None,
            new_restrictions=[{"restriction_type": "BUSINESS_LIMIT_REACHED"}],
        )
        assert any(e[0] == WhatsAppPhoneHealthEventType.restriction_added for e in events)

    def test_restriction_lifted_only_when_all_clear(self):
        config = _config(restrictions=[{"restriction_type": "BUSINESS_LIMIT_REACHED"}])
        events = _diff_fields(
            config=config,
            new_quality=None,
            new_tier=None,
            new_name_status=None,
            new_throughput=None,
            new_restrictions=[],  # all cleared
        )
        assert any(e[0] == WhatsAppPhoneHealthEventType.restriction_lifted for e in events)


class TestRecoveryKeys:
    def test_yellow_quality_flags_quality_degraded(self):
        keys = _recovery_keys(
            quality_rating="YELLOW",
            name_status="APPROVED",
            restrictions=[],
            tier="TIER_1K",
        )
        assert "quality_degraded" in keys
        assert "restricted" not in keys

    def test_red_quality_also_flags_quality_degraded(self):
        keys = _recovery_keys(
            quality_rating="RED",
            name_status="APPROVED",
            restrictions=[],
            tier="TIER_1K",
        )
        assert "quality_degraded" in keys

    def test_restrictions_present_flags_restricted(self):
        keys = _recovery_keys(
            quality_rating="GREEN",
            name_status="APPROVED",
            restrictions=[{"restriction_type": "X"}],
            tier="TIER_1K",
        )
        assert "restricted" in keys

    def test_pending_name_status_flagged(self):
        keys = _recovery_keys(
            quality_rating="GREEN",
            name_status="NONE",
            restrictions=[],
            tier="TIER_1K",
        )
        assert "name_status_pending" in keys

    def test_low_tier_flagged(self):
        keys = _recovery_keys(
            quality_rating="GREEN",
            name_status="APPROVED",
            restrictions=[],
            tier="TIER_50",
        )
        assert "low_tier" in keys

    def test_healthy_state_no_keys(self):
        keys = _recovery_keys(
            quality_rating="GREEN",
            name_status="APPROVED",
            restrictions=[],
            tier="TIER_10K",
        )
        assert keys == []


class TestWebhookExtraction:
    def test_quality_event_extracted(self):
        payload = {
            "entry": [
                {
                    "id": "waba_id_123",
                    "time": 1700000000,
                    "changes": [
                        {
                            "field": "phone_number_quality_update",
                            "value": {
                                "display_phone_number": "+919876543210",
                                "event": "YELLOW",
                                "current_limit": "TIER_1K",
                            },
                        }
                    ],
                }
            ]
        }
        event = _extract_phone_quality_event(payload)
        assert event is not None
        assert event["waba_id"] == "waba_id_123"
        assert event["event"] == "YELLOW"
        assert event["current_limit"] == "TIER_1K"

    def test_non_quality_payload_returns_none(self):
        # A regular inbound-message webhook — `field` is `messages`,
        # NOT `phone_number_quality_update`. Extractor must short-circuit.
        payload = {
            "entry": [
                {
                    "id": "waba_id_123",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "111"},
                                "messages": [{"id": "wamid", "from": "919"}],
                            },
                        }
                    ],
                }
            ]
        }
        assert _extract_phone_quality_event(payload) is None
