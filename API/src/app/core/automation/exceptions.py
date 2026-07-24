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
        super().__init__(f"a trigger named {name!r} already exists in this org")
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


# --- tasks/automation-conditions/ Step 2 ----------------------------


class FieldNotFound(AutomationError):
    """Customer's ``field-values`` request references a field path
    that isn't in the event's ``condition_fields`` spec. Router maps
    to 404."""

    code = "automation.field_not_found"

    def __init__(self, *, event_type: str, field: str) -> None:
        super().__init__(
            f"field {field!r} is not declared on event {event_type!r}'s condition_fields"
        )
        self.event_type = event_type
        self.field = field


class FieldNotEnum(AutomationError):
    """Customer's ``field-values`` request references a field whose
    type is not ``enum`` (e.g. a text or currency field, which
    doesn't have a value pool to lookup). Router maps to 422."""

    code = "automation.field_not_enum"

    def __init__(self, *, event_type: str, field: str, field_type: str) -> None:
        super().__init__(
            f"field {field!r} on event {event_type!r} has type {field_type!r}, "
            f"not 'enum' — only enum fields have a value pool to look up."
        )
        self.event_type = event_type
        self.field = field
        self.field_type = field_type


class ResolverNotRegistered(AutomationError):
    """A ``FieldSpec.enum_resolver`` key doesn't have a matching entry
    in the resolver registry. This is a code bug — the
    ``test_every_field_spec_resolver_key_is_registered`` pin should
    catch it before deploy. Router maps to 500."""

    code = "automation.resolver_not_registered"

    def __init__(self, resolver_key: str) -> None:
        super().__init__(
            f"enum_resolver key {resolver_key!r} is not registered — "
            f"add a matching register_resolver(...) call in "
            f"core.automation.enum_resolvers (or a pack's event_catalog.py)."
        )
        self.resolver_key = resolver_key


__all__ = [
    "AutomationError",
    "DuplicateTriggerName",
    "FieldNotEnum",
    "FieldNotFound",
    "InvalidCondition",
    "MissingTemplateForChannel",
    "ResolverNotRegistered",
    "TriggerNotFound",
]
