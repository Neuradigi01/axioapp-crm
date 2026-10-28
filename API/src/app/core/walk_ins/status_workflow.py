"""Walk-in status state-machine. Keep transitions explicit.

Values match `WalkInStatus` in `core/walk_ins/models.py`:

    browsing  → interested, left
    interested → follow_up, converted, left
    follow_up  → converted, left
    converted  → (terminal)
    left       → browsing   (re-engagement when a visitor returns)

The terminal `converted` state intentionally has no outbound transition:
once a walk-in is recorded as a sale, it stays there. A returning
customer counts as a NEW walk-in row, not a re-opened old one — gives
clean reporting per visit.

Service-level enforcement in `update_walk_in` rejects any status
change that doesn't appear in this map.
"""

from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "browsing": frozenset({"interested", "left"}),
    "interested": frozenset({"follow_up", "converted", "left"}),
    "follow_up": frozenset({"converted", "left"}),
    "converted": frozenset(),
    "left": frozenset({"browsing"}),
}
