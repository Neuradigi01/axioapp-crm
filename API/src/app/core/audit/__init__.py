"""Audit-log module — captures `who did what, when, where` for compliance review.

`audit.log(action, ...)` is a best-effort writer: it persists in an
independent transaction and swallows its own exceptions so the parent
request flow can never be broken by an audit failure. The list
endpoint (`GET /api/v1/audit-logs`) is gated by the `audit.read`
permission.
"""

from src.app.core.audit.service import log

__all__ = ["log"]
