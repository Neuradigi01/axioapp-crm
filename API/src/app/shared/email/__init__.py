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


from src.app.shared.email.log_backend import LogEmailBackend  # noqa: E402

# Module-level default. Production swaps via env-driven wiring.
_backend: EmailBackend = LogEmailBackend()


def get_email_backend() -> EmailBackend:
    """Return the active email backend.

    A future composition root may replace this with an env-driven
    factory; for now the dev `LogEmailBackend` is the only impl.
    """
    return _backend


__all__ = ["Email", "EmailBackend", "get_email_backend"]
