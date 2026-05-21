"""Outbound email plumbing — pluggable backends behind a Protocol.

Only the data shape and the `EmailBackend` Protocol live here. The
default (dev) implementation that logs the email body is in
`log_backend.py`; a production SMTP / SES backend would slot in by
matching the same Protocol and being wired through `get_email_backend()`.

This module is intentionally tiny — Phase 1 of the build didn't ship
an email module, but the invite flow (step 2.5.6) needs one. Real
delivery (Mailgun / SES / SMTP) lands in Phase 6 deployment work; for
now the LogEmailBackend prints the body so dev/test can read the
accept link from the API log and click it manually.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None


class EmailBackend(Protocol):
    async def send(self, email: Email) -> None:
        ...


from config import EMAIL_ENABLED  # noqa: E402

from src.app.shared.email.log_backend import LogEmailBackend  # noqa: E402
from src.app.shared.email.smtp_backend import SmtpEmailBackend  # noqa: E402


def _select_backend() -> EmailBackend:
    return SmtpEmailBackend() if EMAIL_ENABLED else LogEmailBackend()


# Module-level default, chosen at import time from env.
_backend: EmailBackend = _select_backend()


def get_email_backend() -> EmailBackend:
    """Return the active email backend.

    `SmtpEmailBackend` when `EMAIL_ENABLED=true` (delegates to the
    legacy aiosmtplib helper), otherwise `LogEmailBackend` which just
    logs the body so dev can copy the invite link out of the API log.
    """
    return _backend


__all__ = ["Email", "EmailBackend", "get_email_backend"]
