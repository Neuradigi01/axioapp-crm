"""Domain exceptions for the workflows module.

Service / engine / router map these to HTTP statuses:

  * :class:`WorkflowNotFound`        → 404
  * :class:`InvalidGraph`            → 422 (graph reject — payload's
                                     ``reason`` surfaces verbatim)
  * :class:`DuplicateWorkflowName`   → 409
  * :class:`WorkflowLocked`          → 409 (editing an active
                                     marketing workflow)
  * :class:`FolderHasWorkflows`      → 409 (delete on non-empty
                                     folder; ``count`` carries the
                                     blocker count)
  * :class:`ActivationBlocked`       → 422 (graph valid but a
                                     downstream pre-flight refused
                                     — Step 12 wires compliance)
"""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class — every workflow domain error inherits this so
    the router's exception handler can map the family in one line."""


class WorkflowNotFound(WorkflowError):
    """Workflow row missing (or cross-tenant — RLS gives the same
    404 to both)."""


class InvalidGraph(WorkflowError):
    """Graph validator refused. ``reason`` is the human-readable
    explanation surfaced to the router as the 422 detail.

    Mirrors the ``TemplateSyntaxError`` shape from
    :mod:`core.templates.variables` so the editor's error toast
    can render a single line of operator-friendly text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DuplicateWorkflowName(WorkflowError):
    """Org-scoped unique ``(org_id, lower(name))`` already exists.
    The migration's functional index would also raise — this is
    the friendly pre-check so the router 409s cleanly."""


class WorkflowLocked(WorkflowError):
    """Edit attempted on a workflow that's currently ``active`` AND
    ``is_marketing=true``. Same "pause first" model as published
    email templates: operators pause → edit → reactivate so an
    in-flight enrolment doesn't switch graph mid-stream."""


class FolderHasWorkflows(WorkflowError):
    """Delete refused — the folder still has workflows assigned.
    ``count`` surfaces the blocker count so the router can render
    "3 workflows still inside this folder" in the 409 detail."""

    def __init__(self, count: int) -> None:
        super().__init__(f"folder has {count} workflow(s); reassign or archive first")
        self.count = count


class ActivationBlocked(WorkflowError):
    """Graph valid but a downstream pre-flight refused the
    activation. Step 12 (compliance gates) wires the actual
    blockers — until then ``reason='compliance_check_not_implemented'``
    is the placeholder."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ActionNotImplemented(WorkflowError):
    """The action handler is registered (so the graph validator
    accepts it) but the underlying CRM module hasn't shipped yet.
    Step 8 uses this for ``record.create_order`` + ``record.create_quote``
    — the modules will land in future tracks; until then the handler
    raises so the run-history view shows ``error='action_not_implemented'``
    instead of silently no-oping."""

    def __init__(self, action_type: str, reason: str | None = None) -> None:
        message = f"action '{action_type}' not implemented" + (f": {reason}" if reason else "")
        super().__init__(message)
        self.action_type = action_type
        self.reason = reason


class ActionRequiresContactError(WorkflowError):
    """Raised when a workflow run's ``contact_id`` is ``None`` but
    the action handler requires a contact to operate.

    Scheduled workflows (``tasks/workflow-scheduling`` Step 2) can
    fire with ``contact_id=None`` when the schedule row itself
    doesn't target a specific contact. Most action handlers today
    tolerate this via a graceful skip (return ``skip_reason='no_contact_id'``)
    — this exception is the *loud* alternative reserved for a future
    step's per-node ``require_contact: True`` opt-in when the operator
    wants the run to *fail* rather than silently skip.

    Engine catches → marks the step_run ``errored`` with
    ``error='ActionRequiresContactError: <action_type>'``; downstream
    steps do not execute; the schedule's ``next_run_at`` still advances
    (an errored run doesn't block subsequent fires)."""

    def __init__(self, action_type: str) -> None:
        super().__init__(f"action '{action_type}' requires a contact but run.contact_id is None")
        self.action_type = action_type


__all__ = [
    "ActionNotImplemented",
    "ActionRequiresContactError",
    "ActivationBlocked",
    "DuplicateWorkflowName",
    "FolderHasWorkflows",
    "InvalidGraph",
    "WorkflowError",
    "WorkflowLocked",
    "WorkflowNotFound",
]
