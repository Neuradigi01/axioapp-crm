"""Per-org outbound email backend resolution.

The platform's Brevo SMTP account (``contact@neuradigi.com``, wired
through :func:`shared.email.get_email_backend`) stays reserved for
AUTH mail: welcome, forgot-password, email-verification, 2FA/OTP,
subscription/billing notifications, team invites.

For app-generated mail — notification email mirrors, automation Send
Email actions, workflow Send Email nodes, template Test Send —
:func:`resolve_org_sender` looks up the org's own sender identity so
the recipient sees the org's brand instead of the platform's.

Preference order:

  1. Verified :class:`core.email_senders.models.EmailSmtpSender` with
     ``is_default=True`` for the org → :class:`OrgSmtpBackend`.
  2. Any verified :class:`EmailSmtpSender` for the org (oldest first)
     → :class:`OrgSmtpBackend`.
  3. Any :class:`core.email.models.EmailAccount` whose
     ``sync_state != 'disconnected'`` for the org (oldest first) →
     :class:`OrgOauthBackend`. The OAuth gate is deliberately loose:
     ``sync_state`` describes the *inbound* sync lifecycle
     (pending → backfilling → live [→ error]) but outbound send only
     needs a live refresh_token, which is nulled at the same instant
     as the ``disconnected`` flip in :func:`core.email.service.disconnect_account`.
     Requiring ``sync_state='live'`` here made every workflow email
     wait on the 30-day backfill task to complete after OAuth — and
     stay silently broken forever if that task got killed mid-run.
     Ordering by ``connected_at`` gives the oldest-connected mailbox
     first pick, matching the SMTP branch's "first-verified wins" bias.
  4. ``None`` — caller decides how to skip (never silently falls
     back to the platform Brevo sender).
"""

from __future__ import annotations

import logging
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.models import EmailAccount, EmailAccountSyncState
from src.app.core.email_senders import data_access as senders_da
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.shared.email import Email, EmailBackend
from src.utilities.fernet_util import fernet

logger = logging.getLogger(__name__)


def _format_from(row: EmailSmtpSender) -> str:
    if row.display_name:
        return f"{row.display_name} <{row.from_address}>"
    return row.from_address


@dataclass(frozen=True, slots=True)
class OrgSmtpBackend:
    """:class:`shared.email.EmailBackend` backed by an org-supplied
    SMTP sender identity."""

    sender: EmailSmtpSender

    async def send(self, email: Email) -> None:
        password = fernet.decrypt(self.sender.smtp_password_enc)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = email.subject
        msg["From"] = _format_from(self.sender)
        msg["To"] = email.to
        msg.attach(MIMEText(email.body_text, "plain", "utf-8"))
        if email.body_html:
            msg.attach(MIMEText(email.body_html, "html", "utf-8"))

        use_tls = self.sender.tls_mode == "tls"
        start_tls = self.sender.tls_mode == "starttls"

        tls_context: ssl.SSLContext | None = None
        if use_tls or start_tls:
            tls_context = ssl.create_default_context()

        smtp = aiosmtplib.SMTP(
            hostname=self.sender.smtp_host,
            port=self.sender.smtp_port,
            use_tls=use_tls,
            start_tls=False,
            tls_context=tls_context,
            timeout=30.0,
        )
        await smtp.connect()
        try:
            if start_tls:
                await smtp.starttls(tls_context=tls_context)
            await smtp.login(self.sender.smtp_username, password)
            await smtp.send_message(msg)
        finally:
            try:
                await smtp.quit()
            except Exception:  # pragma: no cover — best-effort shutdown
                pass


@dataclass(slots=True)
class OrgOauthBackend:
    """:class:`shared.email.EmailBackend` backed by a live
    :class:`EmailAccount` OAuth mailbox (Gmail or Microsoft).

    Assembles a MIME message from the :class:`Email` dataclass and
    hands it to the provider-specific send helper (which owns daily-
    cap accounting + token refresh)."""

    account: EmailAccount
    session: AsyncSession

    async def send(self, email: Email) -> None:
        provider = (
            self.account.provider.value
            if hasattr(self.account.provider, "value")
            else str(self.account.provider)
        )

        # Build a minimal RFC-5322 message. `EmailMessage` (over
        # MIMEMultipart) plays nicely with both Gmail's `raw`
        # payload and Graph's `sendMail` which both accept
        # base64-encoded raw MIME.
        msg = EmailMessage()
        msg["Subject"] = email.subject
        msg["From"] = (
            f"{self.account.display_name} <{self.account.email_address}>"
            if self.account.display_name
            else self.account.email_address
        )
        msg["To"] = email.to
        msg.set_content(email.body_text)
        if email.body_html:
            msg.add_alternative(email.body_html, subtype="html")

        raw_mime = bytes(msg)

        if provider == "gmail":
            from src.app.core.email.gmail.send import send as gmail_send

            await gmail_send(self.account, self.session, raw_mime=raw_mime)
            return
        if provider == "microsoft":
            from src.app.core.email.microsoft.send import send as ms_send

            await ms_send(self.account, self.session, raw_mime=raw_mime)
            return

        raise RuntimeError(
            f"OrgOauthBackend: unsupported provider {provider!r} for account "
            f"{self.account.id}"
        )


async def resolve_org_sender(
    session: AsyncSession, *, org_id: uuid.UUID
) -> EmailBackend | None:
    """Pick the outbound backend for org-originated mail.

    Returns ``None`` when the org has no verified SMTP sender AND no
    live OAuth mailbox — the caller must skip the send with a
    ``org_sender_not_configured`` reason rather than falling back to
    the platform Brevo sender.
    """
    default_smtp = await senders_da.find_default_verified(session, org_id=org_id)
    if default_smtp is not None:
        return OrgSmtpBackend(sender=default_smtp)

    any_smtp = await senders_da.find_any_verified(session, org_id=org_id)
    if any_smtp is not None:
        return OrgSmtpBackend(sender=any_smtp)

    result = await session.execute(
        select(EmailAccount)
        .where(
            EmailAccount.org_id == org_id,
            EmailAccount.sync_state != EmailAccountSyncState.disconnected,
            EmailAccount.refresh_token_enc.is_not(None),
        )
        .order_by(EmailAccount.connected_at.asc())
        .limit(1)
    )
    oauth = result.scalar_one_or_none()
    if oauth is not None:
        return OrgOauthBackend(account=oauth, session=session)

    return None


__all__ = ["OrgOauthBackend", "OrgSmtpBackend", "resolve_org_sender"]
