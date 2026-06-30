"""Module-level exceptions for the WhatsApp Web integration.

These are raised by the service / sidecar-client layer and mapped to
HTTP status codes by the router. Keeping them in their own file so
both layers can import without circular references.
"""
from __future__ import annotations


class WhatsAppWebError(Exception):
    """Base class — never raised directly."""


class AlreadyConnected(WhatsAppWebError):
    """The org already has an active WhatsApp Web integration; the
    operator must disconnect before re-pairing. Router maps to 409."""


class SidecarUnavailable(WhatsAppWebError):
    """The Node sidecar returned a 5xx or could not be reached at all
    (network error, timeout). Router maps to 502 Bad Gateway."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class SessionNotConnected(WhatsAppWebError):
    """Sidecar reports the session is not in ``connected`` state — used
    by the Step-7 send-message path. Router maps to 409."""


class SidecarRateLimited(WhatsAppWebError):
    """Sidecar's per-session outbound token bucket is empty. Router
    surfaces the ``retry_after_seconds`` so the SPA can back off."""

    def __init__(self, detail: str, *, retry_after_seconds: int = 1) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "AlreadyConnected",
    "SessionNotConnected",
    "SidecarRateLimited",
    "SidecarUnavailable",
    "WhatsAppWebError",
]
