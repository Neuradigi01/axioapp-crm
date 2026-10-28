"""whatsapp-platform-upgrade Step 23 — block-list boundary tests.

Pure-Python coverage of:
  * Phone normalisation (the column-format contract used by both
    inbound webhook + outbound send-guard).
  * STOP-shaped reason validation.
  * Inbound-phone parser on a representative Meta payload.

DB-touching paths (`is_blocked` against a live row, the
immutability of the `ON CONFLICT` constraint, RLS isolation across
tenants) are exercised by the smoke flow — same precedent as
prior steps.

Cases:
  1-4. ``normalise_phone`` strips +, spaces, dashes, parens.
  5.   ``normalise_phone`` returns "" on None / empty.
  6-7. ``_validate_reason`` accepts known + rejects bogus values.
  8.   ``BLOCK_REASONS`` set is stable (5 distinct keys).
  9-11.``parse_inbound_phone`` extracts ``from`` from valid envelope.
 12.   ``parse_inbound_phone`` returns None on status-only payload.
 13.   ``parse_inbound_phone`` returns None on malformed envelope.
 14.   ``BlockedNumberOutbound`` carries phone + reason for audit.
"""

from __future__ import annotations

import pytest

from src.app.core.conversations.adapters.whatsapp import (
    parse_inbound_phone,
)
from src.app.core.integrations.whatsapp.block_list import (
    BLOCK_REASONS,
    BlockedNumberOutbound,
    BlockListError,
    _validate_reason,
    normalise_phone,
)


class TestNormalisePhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+91 99999 88888", "919999988888"),
            ("(212) 555-1212", "2125551212"),
            ("+1-555-867-5309", "15558675309"),
            ("971 50 123 4567", "971501234567"),
            ("9876543210", "9876543210"),
        ],
    )
    def test_digit_only(self, raw, expected):
        assert normalise_phone(raw) == expected

    def test_empty_inputs(self):
        assert normalise_phone(None) == ""
        assert normalise_phone("") == ""
        assert normalise_phone("   ") == ""

    def test_pure_letters_yields_empty(self):
        assert normalise_phone("not a number") == ""


class TestReasonValidation:
    @pytest.mark.parametrize("reason", list(BLOCK_REASONS))
    def test_known_values_accepted(self, reason):
        assert _validate_reason(reason) == reason

    def test_unknown_rejected(self):
        with pytest.raises(BlockListError):
            _validate_reason("dnd")
        with pytest.raises(BlockListError):
            _validate_reason("")

    def test_reasons_are_unique(self):
        # 5 distinct keys, no accidental aliases.
        assert len(set(BLOCK_REASONS)) == len(BLOCK_REASONS)
        assert set(BLOCK_REASONS) == {
            "spam",
            "fraud",
            "requested",
            "harassment",
            "other",
        }


class TestInboundPhoneParser:
    def test_extracts_from_field(self):
        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [{"from": "919999988888", "id": "wamid.X"}]}}]}
            ]
        }
        assert parse_inbound_phone(payload) == "919999988888"

    def test_status_only_payload(self):
        # Meta delivers `statuses` events without a `messages[]` —
        # parser must return None so the block check doesn't fire.
        payload = {
            "entry": [
                {"changes": [{"value": {"statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}
            ]
        }
        assert parse_inbound_phone(payload) is None

    def test_malformed_envelopes(self):
        # Each of these has shape that breaks the dotted path at a
        # different point — none should raise.
        assert parse_inbound_phone({}) is None
        assert parse_inbound_phone({"entry": []}) is None
        assert parse_inbound_phone({"entry": [{"changes": []}]}) is None
        assert parse_inbound_phone({"entry": [{"changes": [{"value": "not-a-dict"}]}]}) is None
        # `from` missing → None.
        assert (
            parse_inbound_phone(
                {"entry": [{"changes": [{"value": {"messages": [{"id": "wamid.X"}]}}]}]}
            )
            is None
        )


class TestBlockedNumberOutbound:
    def test_carries_phone_and_reason(self):
        exc = BlockedNumberOutbound(phone="919999988888", reason="spam")
        assert exc.phone == "919999988888"
        assert exc.reason == "spam"
        assert "919999988888" in str(exc)
        assert "spam" in str(exc)
