"""Typed exceptions for the automation engine.

Each exception inherits :class:`AutomationError` so the router
(Step 3) can map them to HTTP statuses with a single ``except``
clause + a small dispatch table — same pattern templates' workflow
exceptions use.

Service-layer code raises these; the dispatcher (Step 4) catches a
subset (``MissingTemplateForChannel``, ``InvalidCondition``) at run
time and flips the run row to ``status='skipped'`` so the operator
sees the reason in the run-history UI.
"""
from __future__ import annotations

import uuid


class AutomationError(Exception):
    """Base class so a single ``except`` covers every automation-side
    typed failure. Carries an optional ``code`` the router can
    surface as ``detail.code`` for structured error responses."""

    code: str = "automation.error"


class TriggerNotFound(AutomationError):
    """The requested trigger id doesn't exist (or belongs to another
    org — RLS-scoped). Router maps to 404."""

    code = "automation.trigger_not_found"

    def __init__(self, trigger_id: uuid.UUID) -> None:
        super().__init__(f"automation trigger {trigger_id} not found")
        self.trigger_id = trigger_id


class DuplicateTriggerName(AutomationError):
    """A trigger with the same ``lower(name)`` already exists in this
    org. Router maps to 409."""

    code = "automation.duplicate_trigger_name"

    def __init__(self, name: str) -> None:
        super().__init__(
            f"a trigger named {name!r} already exists in this org"
        )
        self.name = name


class InvalidCondition(AutomationError):
    """Condition payload is structurally broken (unknown op, missing
    ``field``, etc.). Router maps to 422."""

    code = "automation.invalid_condition"

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid trigger condition: {reason}")
        self.reason = reason


class MissingTemplateForChannel(AutomationError):
    """``trigger.channel`` doesn't match the linked template's channel
    (e.g. WA trigger pointing at an email template). Router maps to
    422 so the operator can fix in the editor."""

    code = "automation.template_channel_mismatch"

    def __init__(self, *, trigger_channel: str, template_channel: str) -> None:
        super().__init__(
            f"trigger channel {trigger_channel!r} does not match the linked "
            f"template's channel {template_channel!r}"
        )
        self.trigger_channel = trigger_channel
        self.template_channel = template_channel


__all__ = [
    "AutomationError",
    "DuplicateTriggerName",
    "InvalidCondition",
    "MissingTemplateForChannel",
    "TriggerNotFound",
]
