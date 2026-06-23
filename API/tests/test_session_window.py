"""whatsapp-platform-upgrade Step 15 — 24-hour session window tests.

Pure-Python boundary tests around the session-state helper. The
in-session / out-of-session transitions at exactly the 24-hour
boundary are the trickiest behaviour to lock down; the helper is
small + side-effect-free so we can hit every case without a DB.

Cases:
  1. NULL `last_customer_message_at` → out of session.
  2. Just after a customer message → in session, hours_remaining ~24.
  3. 12 hours in → in session, hours_remaining ~12.
  4. Exactly at 24h boundary → out of session (round-down rule).
  5. > 24h (1 minute past) → out of session.
  6. `expires_at` is `last_customer_message_at + 24h` to the second.
  7. `hours_remaining` clamps to 0.0 when out of session.
  8. The helper accepts a custom `now` for deterministic testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.app.core.conversations.whatsapp_session import (
    SESSION_WINDOW,
    compute_session_state,
)


_FIXED_NOW = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)


class TestComputeSessionState:
    def test_null_timestamp_is_out_of_session(self):
        state = compute_session_state(None, now=_FIXED_NOW)
        assert state["in_session"] is False
        assert state["expires_at"] is None
        assert state["hours_remaining"] == 0.0
        assert state["last_customer_message_at"] is None

    def test_fresh_message_is_in_session_with_full_window(self):
        # Customer messaged just now.
        state = compute_session_state(_FIXED_NOW, now=_FIXED_NOW)
        assert state["in_session"] is True
        # Floating-point math: should round to 24.0.
        assert state["hours_remaining"] == 24.0

    def test_twelve_hours_in_still_in_session(self):
        twelve_ago = _FIXED_NOW - timedelta(hours=12)
        state = compute_session_state(twelve_ago, now=_FIXED_NOW)
        assert state["in_session"] is True
        # Float rounding: 12.0 ± floating epsilon.
        assert 11.99 <= state["hours_remaining"] <= 12.01

    def test_exact_24h_boundary_is_out_of_session(self):
        # Spec rounds down at the boundary — "less than 24h" is the
        # in-session predicate, so exactly 24h must flip to out.
        exactly_24h_ago = _FIXED_NOW - SESSION_WINDOW
        state = compute_session_state(
            exactly_24h_ago, now=_FIXED_NOW
        )
        assert state["in_session"] is False
        assert state["hours_remaining"] == 0.0

    def test_just_past_24h_is_out_of_session(self):
        # 24h + 1m → out.
        too_old = _FIXED_NOW - SESSION_WINDOW - timedelta(minutes=1)
        state = compute_session_state(too_old, now=_FIXED_NOW)
        assert state["in_session"] is False
        assert state["hours_remaining"] == 0.0

    def test_expires_at_is_offset_by_window(self):
        msg_time = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)
        state = compute_session_state(msg_time, now=_FIXED_NOW)
        assert state["expires_at"] == datetime(
            2026, 6, 24, 10, 0, 0, tzinfo=timezone.utc
        )

    def test_hours_remaining_clamps_to_zero(self):
        # Way past — make sure we never emit a negative number.
        ancient = _FIXED_NOW - timedelta(days=7)
        state = compute_session_state(ancient, now=_FIXED_NOW)
        assert state["hours_remaining"] == 0.0

    def test_passthrough_last_customer_message_at(self):
        msg_time = _FIXED_NOW - timedelta(hours=3)
        state = compute_session_state(msg_time, now=_FIXED_NOW)
        assert state["last_customer_message_at"] == msg_time
