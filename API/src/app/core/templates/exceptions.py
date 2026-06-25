"""Templates module — domain exceptions.

Service-layer errors that callers (Step 3 router, future automation
+ workflow dispatchers) translate into HTTP responses. Plain Python
exceptions — no FastAPI ``HTTPException`` here so non-HTTP callers
(Celery workers, internal dispatchers) get clean Python semantics.
"""
from __future__ import annotations


class TemplateError(Exception):
    """Base class for template-domain errors."""


class TemplateNotFound(TemplateError):
    """Raised by service reads when no template matches the (org_id, id)
    pair. The router converts to 404."""


class DuplicateTemplateName(TemplateError):
    """Raised on create/rename when ``(org_id, lower(name), channel)``
    collides with an existing row. The functional unique index installed
    by migration 0117 enforces it at the DB layer; the service raises
    this so the router can return a structured 409 with the offending
    name instead of a generic IntegrityError."""

    def __init__(self, name: str, channel: str) -> None:
        super().__init__(
            f"a {channel} template named '{name}' already exists in this org"
        )
        self.name = name
        self.channel = channel


class TemplateLocked(TemplateError):
    """Raised when ``update_template`` is called on a template whose
    ``internal_status`` is in (``in_review``, ``approved``, ``published``).

    The workflow (Step 4) moves a template back to ``draft`` via reject
    / request_changes; only then can the body be edited. The router
    returns 409 with the current status.
    """

    def __init__(self, status: str) -> None:
        super().__init__(
            f"template is locked for editing (current status: {status})"
        )
        self.status = status


class InvalidWorkflowTransition(TemplateError):
    """Raised by the workflow state machine when the requested action
    is illegal from the current state (e.g. ``approve`` on a ``draft``
    template). Router maps to 409.
    """

    def __init__(
        self,
        *,
        current: str,
        action: str,
        hint: str | None = None,
    ) -> None:
        msg = (
            f"cannot {action} a template that is currently {current!r}"
        )
        if hint:
            msg = f"{msg} ({hint})"
        super().__init__(msg)
        self.current = current
        self.action = action
        self.hint = hint


class SelfApproveBlocked(TemplateError):
    """Raised by :func:`approve` when the reviewer is the template's
    author and the org has not opted into self-approval. Router maps
    to 409.
    """

    def __init__(self) -> None:
        super().__init__(
            "reviewer cannot be the template's author; ask a different "
            "reviewer to approve, or enable "
            "template_review_self_approve_allowed in org settings"
        )


class PublishBlockedByExternal(TemplateError):
    """Raised by :func:`publish` when ``external_status`` is not in
    (``n_a``, ``approved``). The router maps to 409 with the current
    external status so the UI can prompt the operator to wait / resubmit.
    """

    def __init__(self, *, external_status: str) -> None:
        super().__init__(
            "cannot publish a template whose external review status is "
            f"{external_status!r}; resolve external review first"
        )
        self.external_status = external_status
