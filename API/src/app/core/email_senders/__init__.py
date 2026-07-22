"""Per-org outbound email sender identities.

Complements :mod:`core.email` (Gmail/Microsoft OAuth mailboxes) and
:mod:`core.email_sender_setup` (SPF/DKIM/DMARC domain verification) by
adding a third path: manual SMTP credentials the org supplies + a
6-digit verification code the org confirms on the ``from_address``
inbox.

The module exposes a unified list endpoint that merges verified SMTP
senders with live OAuth ``EmailAccount`` mailboxes so the frontend
integrations page can render one "Email Sender" card regardless of
which transport backs the send.

``shared.email.org_sender.resolve_org_sender`` reads this table and
the ``tbl_email_accounts`` table to decide which backend the
notifications-mirror, automation Send Email, workflow Send Email, and
template Test Send code paths use — the platform Brevo SMTP is
reserved for auth mail (welcome, verify, forgot password, OTP,
subscription/billing, invites).
"""

from src.app.core.email_senders.router import router

__all__ = ["router"]
