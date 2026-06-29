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
        super().__init__(
            f"folder has {count} workflow(s); reassign or archive first"
        )
        self.count = count


class ActivationBlocked(WorkflowError):
    """Graph valid but a downstream pre-flight refused the
    activation. Step 12 (compliance gates) wires the actual
    blockers — until then ``reason='compliance_check_not_implemented'``
    is the placeholder."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "ActivationBlocked",
    "DuplicateWorkflowName",
    "FolderHasWorkflows",
    "InvalidGraph",
    "WorkflowError",
    "WorkflowLocked",
    "WorkflowNotFound",
]
