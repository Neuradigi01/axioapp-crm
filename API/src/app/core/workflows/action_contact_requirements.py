"""Classifier: which action types require ``run.contact_id`` to be
set to fire meaningfully?

Context (``tasks/workflow-scheduling`` Step 2):
    Scheduled workflows can fire with ``contact_id=None`` when the
    schedule row itself doesn't target a specific contact (README
    Cases §13). Every action handler in ``core/workflows/actions/``
    already handles null contact gracefully — either by no-op-ing or
    by returning ``skip_reason='no_contact_id'``. This module gives
    callers a way to *query* the classification without importing
    every handler.

    The engine could use this to eagerly raise
    :class:`ActionRequiresContactError` before dispatch instead of
    letting the handler skip — a future refinement gated behind an
    opt-in per-node ``require_contact: True`` flag. Not on by
    default for v1 because the existing skip-reason path is already
    surfaced in Step 19's run-history UI, and flipping to "raise
    loudly" would regress existing workflows.

Classification rules:
    * Contact-required — the action's core semantics depend on a
      contact record (send to a person, create a record attached to
      them, tag them, route them). NULL contact = the action can't
      do its job.
    * Contact-optional — the action operates on flow state, org-wide
      records, or an explicit non-contact target (webhook, internal
      notify, log). NULL contact is fine.
"""

from __future__ import annotations

# Actions whose core purpose requires a contact. Kept as a frozenset
# for O(1) membership. Sourced from the ``register_action(...)`` calls
# across ``core/workflows/actions/``.
CONTACT_REQUIRED_ACTIONS: frozenset[str] = frozenset(
    {
        # send.* — every channel resolves recipient from contact.
        "send.email",
        "send.slack",
        "send.whatsapp",
        # record.* attached to a contact / lead.
        "record.create_appointment",
        "record.create_invoice",
        "record.create_note",
        "record.create_order",
        "record.create_quote",
        "record.create_task",
        "record.update_contact_field",
        "record.update_lead_field",
        "record.update_lead_stage",
        # lifecycle.* — state changes on the contact.
        "lifecycle.archive_contact",
        "lifecycle.block_contact",
        "lifecycle.enroll_in_sequence",
        "lifecycle.enroll_in_workflow",
        "lifecycle.mark_converted",
        "lifecycle.mark_unsubscribed",
        "lifecycle.remove_from_sequence",
        "lifecycle.remove_from_workflow",
        # routing.* — assigns a user to the contact's record.
        "routing.least_loaded",
        "routing.round_robin",
        "routing.skill",
        "routing.specific_user",
        "routing.territory",
        # tagging.* — attaches tags / list membership / score to a contact.
        "tagging.add_tag",
        "tagging.remove_tag",
        "tagging.add_to_list",
        "tagging.remove_from_list",
        "tagging.set_lead_score",
    }
)


#: Actions that operate without a contact (flow control, admin-side
#: notifications, webhooks). Explicit — not derived by inversion —
#: so a newly-registered action is neither "required" nor "optional"
#: by default; the test matrix will fail until it's classified.
CONTACT_OPTIONAL_ACTIONS: frozenset[str] = frozenset(
    {
        # Built-ins registered by actions/__init__.py.
        "trigger",
        "flow.wait",
        "flow.wait_for_event",
        "flow.end",
        # Branch nodes — evaluate conditions on the payload / context;
        # contact reference is via variable lookup, tolerates None.
        "branch.if",
        "branch.switch",
        # flow_control — internal orchestration + admin-side ops.
        "flow_control.wait",
        "flow_control.wait_for_event",
        "flow_control.ab_split",
        "flow_control.goal",
        "flow_control.call_webhook",
        "flow_control.log_internal_note",
        "flow_control.notify_user",
    }
)


def requires_contact(action_type: str) -> bool:
    """True iff ``action_type`` is in :data:`CONTACT_REQUIRED_ACTIONS`.
    Unknown action types return False (the engine's dispatcher raises
    :class:`ActionNotRegistered` anyway on resolve — no need for the
    classifier to double-report)."""
    return action_type in CONTACT_REQUIRED_ACTIONS


def is_classified(action_type: str) -> bool:
    """True iff ``action_type`` appears in either classification set.
    Pin-test uses this to ensure every registered action is classified
    exactly once — an unclassified action means someone added a new
    handler without updating this module."""
    return action_type in CONTACT_REQUIRED_ACTIONS or action_type in CONTACT_OPTIONAL_ACTIONS


__all__ = [
    "CONTACT_OPTIONAL_ACTIONS",
    "CONTACT_REQUIRED_ACTIONS",
    "is_classified",
    "requires_contact",
]
