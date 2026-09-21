"""Exception hierarchy for :mod:`api_client`.

Callers pattern-match on these to render HTTP responses correctly at
the router boundary (401 → 500 internal misconfig, 404 → 404 to
client, 429 → 503 back-pressure, provider 5xx → 502, shape mismatch
→ 500 with logged detail).

Every exception carries the raw HTTP status when applicable and the
first 500 chars of the response body for operator diagnostics — the
body is truncated so a Mailgun HTML error page doesn't fill our logs.
"""

from __future__ import annotations


class MailgunApiError(Exception):
    """Base for every mailgun-api failure. Never raised directly."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body_preview: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body_preview = body_preview


class MailgunAuthError(MailgunApiError):
    """401 from Mailgun — API key is missing, expired, or wrong tier.

    Almost never a customer's fault; surfaces as a 500 internal error
    at the router boundary with a "misconfigured Mailgun API key"
    detail. Operator sees the audit event + secret rotation is a fix.
    """


class MailgunNotFound(MailgunApiError):
    """404 from Mailgun — the domain doesn't exist at the provider.

    Legitimate cause when a caller passes a domain we've never
    claimed OR when the Mailgun-side row was deleted out of band
    (support-triggered scrub, etc.). Router maps to 404 for the
    client.
    """


class MailgunRateLimited(MailgunApiError):
    """429 from Mailgun — account-wide quota hit.

    Retry-After header from Mailgun (if present) is stashed on
    :attr:`retry_after_seconds`; caller can honour it for a graceful
    back-off. Router maps to 503 with the same retry hint.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body_preview: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(
            message, status_code=status_code, body_preview=body_preview
        )
        self.retry_after_seconds = retry_after_seconds


class MailgunProviderError(MailgunApiError):
    """Mailgun returned 5xx AFTER our retry budget was exhausted.

    Distinct from a transient 502/503 the client retries transparently
    — this exception means the retries also failed and the caller must
    surface upstream (router: 502 Bad Gateway). Operator sees the
    outage in Mailgun's status page + our audit trail.
    """


class MailgunResponseInvalid(MailgunApiError):
    """Mailgun returned 2xx but the body doesn't match our expected shape.

    Symptoms: missing top-level ``domain`` key, malformed
    ``sending_dns_records`` array, non-JSON body from an intermediary
    edge cache. Router maps to 500; operator investigates whether
    Mailgun's contract drifted (see DISCOVERY-NOTES.md).
    """


__all__ = [
    "MailgunApiError",
    "MailgunAuthError",
    "MailgunNotFound",
    "MailgunRateLimited",
    "MailgunProviderError",
    "MailgunResponseInvalid",
]
