"""Dev email backend — logs the body, sends nothing.

Used everywhere production email isn't wired yet (currently every
environment). When SMTP / SES lands, swap via `shared/email/__init__`'s
`get_email_backend()` — callers don't change.

The log line is deliberately readable and grep-able so an engineer can
copy an invite link out of `docker logs template_api-api-1 | grep email`
and click it in the browser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("src.app.shared.email")


@dataclass(frozen=True, slots=True)
class LogEmailBackend:
    """Concrete `EmailBackend` impl that just logs the payload."""

    async def send(self, email) -> None:  # type: ignore[no-untyped-def]
        # Import lazily to avoid the circular shape with `__init__`.
        from src.app.shared.email import Email

        if not isinstance(email, Email):
            raise TypeError(f"expected Email, got {type(email).__name__}")
        logger.info(
            "[email] to=%s | subject=%r\n----- body -----\n%s\n----- end -----",
            email.to,
            email.subject,
            email.body_text,
        )
