"""Null-contact classification matrix — pins which action types
require ``run.contact_id`` and which tolerate ``None``.

Context: scheduled workflows can fire with ``contact_id=None``
(``tasks/workflow-scheduling`` Step 2 README Cases §13). Every
registered action must be classified in
``core/workflows/action_contact_requirements.py`` so future
consumers (engine pre-flight, Builder UI's warning) can query the
answer without importing every handler.

This test is the drift-detector: any new ``register_action(...)``
that isn't classified fails the module-import assertion.
"""

from __future__ import annotations

from src.app.core.workflows.action_contact_requirements import (
    CONTACT_OPTIONAL_ACTIONS,
    CONTACT_REQUIRED_ACTIONS,
    is_classified,
    requires_contact,
)

# Importing the action modules registers them into the registry
# (side-effect imports mirroring the engine's own import order).
from src.app.core.workflows.actions import (  # noqa: F401
    flow_control,
    lifecycle,
    list_registered,
    records,
    routing,
    send,
    tagging,
)


def test_every_registered_action_is_classified():
    """Drift-detector: a new ``register_action(...)`` without a
    classification entry fails here."""
    unclassified = [a for a in list_registered() if not is_classified(a)]
    assert not unclassified, (
        f"the following registered actions are not classified in "
        f"action_contact_requirements.py: {unclassified}. "
        "Add each to CONTACT_REQUIRED_ACTIONS or CONTACT_OPTIONAL_ACTIONS."
    )


def test_no_action_appears_in_both_sets():
    overlap = CONTACT_REQUIRED_ACTIONS & CONTACT_OPTIONAL_ACTIONS
    assert not overlap, f"actions appear in both sets: {overlap}"


def test_requires_contact_returns_true_for_send_email():
    assert requires_contact("send.email") is True


def test_requires_contact_returns_false_for_flow_wait():
    assert requires_contact("flow.wait") is False


def test_requires_contact_returns_false_for_unknown_action():
    """Unknown → False. Engine's dispatch will raise ActionNotRegistered
    on resolve, so the classifier doesn't need to double-report."""
    assert requires_contact("__nonsense__") is False


def test_send_channels_all_require_contact():
    for channel in ("send.email", "send.slack", "send.whatsapp"):
        assert requires_contact(channel), f"{channel} should require contact"


def test_tagging_actions_all_require_contact():
    for a in ("tagging.add_tag", "tagging.remove_tag", "tagging.set_lead_score"):
        assert requires_contact(a), f"{a} should require contact"


def test_flow_control_and_branches_dont_require_contact():
    for a in (
        "flow_control.wait",
        "flow_control.wait_for_event",
        "flow_control.notify_user",
        "flow_control.call_webhook",
        "branch.if",
        "branch.switch",
    ):
        assert not requires_contact(a), f"{a} should NOT require contact"
