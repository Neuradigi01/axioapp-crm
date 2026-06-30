"""SMTP email backend — sends via the legacy aiosmtplib helper.

Delegates to `src.utilities.app_utils.send_mail_async`, which is the
working aiosmtplib client the existing template already uses for
welcome / verification / password-reset mails. Wiring through it keeps
one SMTP path in the codebase rather than duplicating the connect /
login / send_message dance.

Selection happens in `shared/email/__init__.py` based on
`config.EMAIL_ENABLED`. If sending fails (auth error, network), we log
the failure and swallow — invite / OTP flows must not 500 because the
mail server hiccuped; the user can resend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("src.app.shared.email")


@dataclass(frozen=True, slots=True)
class SmtpEmailBackend:
    """Concrete `EmailBackend` impl backed by aiosmtplib (legacy helper)."""

    async def send(self, email) -> None:  # type: ignore[no-untyped-def]
        from src.app.shared.email import Email
        from src.utilities.app_utils import send_mail_async

        if not isinstance(email, Email):
            raise TypeError(f"expected Email, got {type(email).__name__}")

        html_body = email.body_html or email.body_text
        ok, detail = await send_mail_async(email.to, email.subject, html_body)
        if not ok:
            logger.error(
                "[email] SMTP send failed to=%s subject=%r — %s",
                email.to,
                email.subject,
                detail,
            )
