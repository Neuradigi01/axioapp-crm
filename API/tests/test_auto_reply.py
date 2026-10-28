"""whatsapp-platform-upgrade Step 16 — auto-reply tests.

Pure-Python boundary tests around the helpers — variable
substitution and business-hours evaluation. Pipeline integration
(dispatch_auto_replies → adapter.send) is covered end-to-end by the
broader conversations test suite once the migration lands.

Cases:
  1. `substitute_variables` swaps known keys.
  2. Unknown placeholders pass through untouched.
  3. NULL contact / org → empty-string substitution (no crash).
  4. `is_within_business_hours` returns True inside an interval.
  5. Returns False outside intervals.
  6. Returns True when hours is None or empty (always-open default).
  7. Returns False on the wrong weekday.
  8. Handles split-shift intervals (10-13 + 14-19).
  9. Malformed interval (bad HH:MM) is silently skipped.
 10. Multiple matching days don't double-count (we just return True).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from src.app.core.integrations.whatsapp.auto_reply import (
    is_within_business_hours,
    substitute_variables,
)

# Mon 2026-06-22 11:00 UTC — a typical "in business hours" time for
# the tests that follow.
_MON_11AM = datetime(2026, 6, 22, 11, 0, 0, tzinfo=UTC)
_MON_3AM = datetime(2026, 6, 22, 3, 0, 0, tzinfo=UTC)
_SUN_3PM = datetime(2026, 6, 28, 15, 0, 0, tzinfo=UTC)


def _contact(full_name: str | None = "Asha Kumar") -> SimpleNamespace:
    return SimpleNamespace(full_name=full_name)


def _org(name: str | None = "Neuradigi") -> SimpleNamespace:
    return SimpleNamespace(name=name)


class TestSubstituteVariables:
    def test_swaps_known_keys(self):
        out = substitute_variables(
            "Hello {{contact.first_name}}, welcome to {{org.name}}!",
            contact=_contact("Asha Kumar"),
            org=_org("Neuradigi"),
        )
        assert out == "Hello Asha, welcome to Neuradigi!"

    def test_unknown_placeholder_passthrough(self):
        out = substitute_variables(
            "Visit {{org.url}} for more.",
            contact=_contact(),
            org=_org(),
        )
        assert out == "Visit {{org.url}} for more."

    def test_full_name_token(self):
        out = substitute_variables(
            "Hi {{contact.full_name}}.",
            contact=_contact("Asha Kumar"),
            org=_org(),
        )
        assert out == "Hi Asha Kumar."

    def test_null_contact_renders_empty(self):
        out = substitute_variables("Hi {{contact.first_name}}!", contact=None, org=_org())
        # Empty-string substitution rather than a NameError or
        # crash — the operator sees a slightly-awkward "Hi !" rather
        # than a 500.
        assert out == "Hi !"

    def test_empty_text(self):
        out = substitute_variables("", contact=_contact(), org=_org())
        assert out == ""


class TestBusinessHours:
    def test_inside_interval(self):
        hours = [{"day": 0, "intervals": [{"open": "10:00", "close": "19:00"}]}]
        assert is_within_business_hours(hours, now=_MON_11AM) is True

    def test_outside_interval(self):
        hours = [{"day": 0, "intervals": [{"open": "10:00", "close": "19:00"}]}]
        assert is_within_business_hours(hours, now=_MON_3AM) is False

    def test_none_treated_as_always_open(self):
        # If the operator hasn't configured hours, we err on "always
        # open" so out-of-hours auto-reply never spams them.
        assert is_within_business_hours(None, now=_MON_3AM) is True

    def test_empty_list_treated_as_always_open(self):
        assert is_within_business_hours([], now=_MON_3AM) is True

    def test_wrong_weekday_returns_false(self):
        # Mon 10-19 schedule, evaluated on Sunday → closed.
        hours = [{"day": 0, "intervals": [{"open": "10:00", "close": "19:00"}]}]
        assert is_within_business_hours(hours, now=_SUN_3PM) is False

    def test_split_shift_inside_second_interval(self):
        # 10-13, closed for lunch, 14-19 — checking at 15:00.
        hours = [
            {
                "day": 6,  # Sunday in this test
                "intervals": [
                    {"open": "10:00", "close": "13:00"},
                    {"open": "14:00", "close": "19:00"},
                ],
            }
        ]
        assert is_within_business_hours(hours, now=_SUN_3PM) is True

    def test_split_shift_in_lunch_gap_returns_false(self):
        hours = [
            {
                "day": 6,
                "intervals": [
                    {"open": "10:00", "close": "13:00"},
                    {"open": "14:00", "close": "19:00"},
                ],
            }
        ]
        lunchtime = datetime(2026, 6, 28, 13, 30, 0, tzinfo=UTC)
        assert is_within_business_hours(hours, now=lunchtime) is False

    def test_malformed_interval_skipped(self):
        # Garbled "open" string — the helper logs + skips that row
        # rather than crashing the inbound webhook handler.
        hours = [
            {
                "day": 0,
                "intervals": [
                    {"open": "not-a-time", "close": "19:00"},
                    {"open": "10:00", "close": "19:00"},
                ],
            }
        ]
        assert is_within_business_hours(hours, now=_MON_11AM) is True

    def test_at_open_boundary_inclusive(self):
        hours = [{"day": 0, "intervals": [{"open": "10:00", "close": "19:00"}]}]
        # 10:00 on Monday — open_t <= current < close_t makes the
        # opening boundary inclusive.
        at_open = datetime(2026, 6, 22, 10, 0, 0, tzinfo=UTC)
        assert is_within_business_hours(hours, now=at_open) is True

    def test_at_close_boundary_exclusive(self):
        hours = [{"day": 0, "intervals": [{"open": "10:00", "close": "19:00"}]}]
        at_close = datetime(2026, 6, 22, 19, 0, 0, tzinfo=UTC)
        assert is_within_business_hours(hours, now=at_close) is False
