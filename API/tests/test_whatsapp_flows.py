"""whatsapp-platform-upgrade Step 25 — WhatsApp Flows boundary tests.

Pure-Python coverage of:
  * Bundled template loader (`load_template` + `available_templates`).
  * `parse_scheduled_at` date+time parsing (appointment auto-action).
  * `parse_webhook` extracts ``nfm_reply`` form payloads correctly.
  * Template JSON shape — at least one screen with a terminal action.

Meta Graph calls (publish / asset upload / test send) are exercised
via the smoke flow against a sandbox WABA — same precedent as
prior steps.

Cases:
  1.  ``load_template('appointment_booking')`` returns the bundled JSON
      with at least one screen + a Footer ``complete`` action.
  2.  ``load_template('lead_capture')`` returns valid JSON.
  3.  ``load_template('feedback')`` returns valid JSON.
  4.  ``load_template('custom')`` returns an empty skeleton.
  5.  ``load_template('bogus')`` raises ``FlowsServiceError``.
  6.  ``available_templates`` returns the 4 keys with labels +
      descriptions.
  7.  ``_parse_scheduled_at`` produces a tz-aware UTC datetime for
      ``YYYY-MM-DD`` + ``HH:MM``.
  8.  ``_parse_scheduled_at`` returns None on missing date.
  9.  ``_parse_scheduled_at`` falls back to ISO-only date string.
 10.  ``_parse_scheduled_at`` returns None on garbage.
 11.  ``parse_webhook`` lifts ``nfm_reply.response_json`` (dict) into
      ``attachments[0].form_data``.
 12.  ``parse_webhook`` parses ``response_json`` when it's a JSON
      string.
 13.  ``parse_webhook`` falls back to empty dict on malformed
      ``response_json``.
 14.  Template JSON for every bundled file has a top-level
      ``version`` and ``screens`` array.
"""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter
from src.app.core.integrations.whatsapp.flows_service import (
    FlowsServiceError,
    _parse_scheduled_at,
    available_templates,
    load_template,
)


def _adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id="phone-x",
        token="token-x",
        app_secret="secret-x",
        verify_token="verify-x",
        api_version="v19.0",
    )


def _wrap_message(message: dict) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


class TestTemplateLoader:
    @pytest.mark.parametrize(
        "category",
        ["appointment_booking", "lead_capture", "feedback"],
    )
    def test_bundled_templates_load(self, category):
        tpl = load_template(category)
        assert isinstance(tpl, dict)
        assert tpl.get("version")
        screens = tpl.get("screens")
        assert isinstance(screens, list) and len(screens) >= 1

    def test_bundled_templates_have_footer_complete(self):
        # Every bundled template's terminal screen must include a
        # Footer with `on-click-action.name == 'complete'` so the
        # Meta runtime knows to fire `nfm_reply`. Walk children
        # recursively.
        def has_complete_footer(node):
            if isinstance(node, dict):
                if (
                    node.get("type") == "Footer"
                    and isinstance(node.get("on-click-action"), dict)
                    and node["on-click-action"].get("name") == "complete"
                ):
                    return True
                for v in node.values():
                    if has_complete_footer(v):
                        return True
            elif isinstance(node, list):
                for child in node:
                    if has_complete_footer(child):
                        return True
            return False

        for cat in ("appointment_booking", "lead_capture", "feedback"):
            assert has_complete_footer(load_template(cat)), cat

    def test_custom_returns_empty_skeleton(self):
        tpl = load_template("custom")
        assert tpl["screens"][0]["id"] == "CUSTOM"
        assert tpl["screens"][0]["terminal"] is True

    def test_unknown_category_raises(self):
        with pytest.raises(FlowsServiceError):
            load_template("bogus_category")

    def test_available_templates_returns_four(self):
        rows = available_templates()
        keys = {r["key"] for r in rows}
        assert keys == {
            "appointment_booking",
            "lead_capture",
            "feedback",
            "custom",
        }
        for row in rows:
            assert row["label"]
            assert row["description"]


class TestParseScheduledAt:
    def test_date_plus_time(self):
        ts = _parse_scheduled_at({"preferred_date": "2026-07-15", "preferred_time": "14:30"})
        assert ts is not None
        assert ts.tzinfo is not None
        assert ts.year == 2026 and ts.month == 7 and ts.day == 15
        assert ts.hour == 14 and ts.minute == 30
        assert ts.utcoffset() == UTC.utcoffset(None)

    def test_missing_date(self):
        assert _parse_scheduled_at({"preferred_time": "14:30"}) is None

    def test_missing_time_falls_back_to_10am(self):
        ts = _parse_scheduled_at({"preferred_date": "2026-07-15"})
        assert ts is not None
        assert ts.hour == 10 and ts.minute == 0

    def test_garbage_inputs(self):
        assert _parse_scheduled_at({"preferred_date": "not-a-date"}) is None
        assert _parse_scheduled_at({}) is None
        assert _parse_scheduled_at({"preferred_date": "", "preferred_time": ""}) is None


class TestNfmReplyParser:
    def test_dict_response_json(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.X",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow-token-x",
                    "body": "Booking confirmed",
                    "response_json": {
                        "preferred_date": "2026-07-15",
                        "preferred_time": "14:30",
                        "service": "consultation",
                    },
                },
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        nfm = next(
            (a for a in parsed.attachments if a.get("type") == "nfm_reply"),
            None,
        )
        assert nfm is not None
        assert nfm["flow_token"] == "flow-token-x"
        assert nfm["form_data"]["service"] == "consultation"
        # Text falls back to the `body` field so the inbox renders
        # something readable.
        assert parsed.text == "Booking confirmed"

    def test_json_string_response_json(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.Y",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow-token-y",
                    "response_json": json.dumps({"full_name": "Ada", "email": "ada@x.test"}),
                },
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        nfm = next(
            (a for a in parsed.attachments if a.get("type") == "nfm_reply"),
            None,
        )
        assert nfm is not None
        assert nfm["form_data"] == {
            "full_name": "Ada",
            "email": "ada@x.test",
        }

    def test_malformed_response_json_yields_empty_dict(self):
        msg = {
            "from": "919999988888",
            "id": "wamid.Z",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow-token-z",
                    "response_json": "{not json",
                },
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        nfm = next(
            (a for a in parsed.attachments if a.get("type") == "nfm_reply"),
            None,
        )
        assert nfm is not None
        assert nfm["form_data"] == {}
        # Text falls back to the placeholder since `body` is also missing.
        assert parsed.text == "[Flow submission]"

    def test_missing_response_json_yields_empty_dict(self):
        # Edge case: Meta might omit `response_json` entirely on some
        # validation failures. Parser must not crash.
        msg = {
            "from": "919999988888",
            "id": "wamid.W",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {"name": "flow-token-w"},
            },
        }
        parsed = _adapter().parse_webhook(_wrap_message(msg))
        nfm = next(
            (a for a in parsed.attachments if a.get("type") == "nfm_reply"),
            None,
        )
        assert nfm is not None
        assert nfm["form_data"] == {}
