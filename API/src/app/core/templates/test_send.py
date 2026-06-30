"""Per-channel test-send orchestration for the template library.

One public coroutine, :func:`dispatch_test_send`, lets the operator
ship a rendered template to a chosen recipient *before* it's
published — the classic "send a sample to my own phone / inbox"
flow. Every send writes a row to ``tbl_message_template_test_sends``
so the operator can prove later that the template was vetted.

Channel coverage:

* **Email** — uses the generic outbound backend at
  :func:`shared.email.get_email_backend` (same path the invite +
  password-reset flows use). Doesn't require the recipient to be an
  existing ``tbl_contacts`` row — important because the operator
  typically tests by emailing themselves.
* **WhatsApp** — uses :func:`resolve_whatsapp_adapter` with the
  org's default phone number (or a phone the conversation already
  pinned, where applicable). Sends the rendered body as plain text.
  Subject to Meta's 24-hour session rule — the recipient must have
  messaged the WABA in the last 24h for an arbitrary text send to
  land; outside that window Meta will reject with a re-engagement
  error which the operator sees as the adapter's exception.
* **SMS / FB Messenger / IG Direct / push / web** — :class:`TestSendNotSupported`
  raised. Each channel ships its own test path in the later step
  that adds the adapter (SMS at Step 12, FB/IG/push at Step 13).

Recipient validation is intentionally light: an email-shape regex
for email, digits-only / E.164-without-leading-plus for phone.
Anything tighter would refuse perfectly valid edge cases (Indian
DID numbers, technical-mailbox emails).

Audit-row write is best-effort *after* the adapter returns: a
successful send always logs; a failed send logs nothing here but
the calling router surfaces the adapter's exception verbatim so
the operator sees exactly what went wrong.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.exceptions import (
    InvalidRecipient,
    TestSendNotSupported,
)
from src.app.core.templates.models import (
    MessageTemplateTestSend,
)
from src.app.core.templates.service import get_template
from src.app.core.templates.variables import resolve

logger = logging.getLogger(__name__)


# RFC-5322 is way too permissive in practice; this is the
# "looks-like-an-email" regex every web-form validator settles on.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# E.164 without the leading `+` — Meta accepts this shape. Range 8-15
# covers every national format we care about (India = 12 incl. country
# code, US = 11, UK = 12, UAE = 12, etc.).
_PHONE_RE = re.compile(r"^\d{8,15}$")


def _validate_recipient(channel: ConversationChannel, recipient: str) -> str:
    """Normalise + validate the recipient string for the channel.

    Returns the cleaned recipient (whitespace stripped, leading ``+``
    removed for phone). Raises :class:`InvalidRecipient` if the shape
    doesn't match.
    """
    recipient = recipient.strip()
    if not recipient:
        raise InvalidRecipient(
            channel=channel.value,
            recipient=recipient,
            reason="recipient is empty",
        )

    if channel == ConversationChannel.email:
        if not _EMAIL_RE.match(recipient):
            raise InvalidRecipient(
                channel=channel.value,
                recipient=recipient,
                reason="not a valid email address",
            )
        return recipient

    if channel in (
        ConversationChannel.whatsapp,
        ConversationChannel.sms,
    ):
        cleaned = recipient.lstrip("+").replace(" ", "").replace("-", "")
        if not _PHONE_RE.match(cleaned):
            raise InvalidRecipient(
                channel=channel.value,
                recipient=recipient,
                reason="phone must be 8-15 digits (E.164 without +)",
            )
        return cleaned

    # FB / IG / push: validation lives in the channel-specific adapter
    # when it lands. For now we accept the raw string + raise
    # TestSendNotSupported in the dispatch path.
    return recipient


def _build_context(extra: dict[str, Any] | None) -> dict[str, Any]:
    """Start with a minimal context (just ``{{org.*}}`` placeholders)
    and overlay any caller-supplied sample data. The org's real name
    + support contact pulls from the live row would be nicer but
    we'd need a tenants data-access call — for v1 the caller can
    supply the sample context explicitly when they want it filled."""
    ctx: dict[str, Any] = {
        "contact": {
            "first_name": "Sample",
            "last_name": "Recipient",
            "full_name": "Sample Recipient",
        },
        "org": {"name": ""},
        "sender": {"name": ""},
    }
    if extra:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(ctx.get(key), dict):
                ctx[key] = {**ctx[key], **value}
            else:
                ctx[key] = value
    return ctx


async def _dispatch_email(
    *,
    recipient: str,
    subject: str,
    body: str,
) -> str | None:
    """Ship the rendered email via the generic outbound backend.

    Returns the provider's message id when the backend supplies one;
    the default ``SmtpEmailBackend`` doesn't surface an id today, so
    ``None`` is the common case. The audit row still gets written —
    operators check their inbox to confirm receipt.
    """
    from src.app.shared.email import Email, get_email_backend

    backend = get_email_backend()
    await backend.send(Email(to=recipient, subject=subject, body_text=body, body_html=None))
    return None


async def _dispatch_whatsapp(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    recipient: str,
    body: str,
) -> str | None:
    """Ship the rendered body as a plain WhatsApp text message.

    Goes through the org's default WhatsApp config (oldest connected
    phone) via :func:`resolve_whatsapp_adapter`. The 24-hour session
    rule applies: Meta refuses free-text sends to a number that
    hasn't messaged the WABA in the last 24h. The operator sees that
    as a 4xx from the adapter; the router surfaces the message.

    Future enhancement: route test-send through an approved-template
    path so it works outside the session window. Out of scope for
    this step.
    """
    from src.app.core.conversations.adapters.whatsapp import (
        resolve_whatsapp_adapter,
    )

    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send(
        org_id=org_id,
        external_id=recipient,
        text=body,
        attachments=[],
    )
    return ref.channel_message_id


async def dispatch_test_send(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    recipient: str,
    user_id: uuid.UUID | None,
    sample_context: dict[str, Any] | None = None,
) -> MessageTemplateTestSend:
    """Render the template against a sample context, send it to
    ``recipient`` via the channel's adapter, and write an audit row.

    Raises:
      :class:`TemplateNotFound` when the template id doesn't belong
        to the org.
      :class:`InvalidRecipient` when the recipient shape is wrong
        for the channel.
      :class:`TestSendNotSupported` when the channel has no test
        transport wired yet (SMS / FB / IG / push / web).

    Any exception raised by the channel adapter (e.g. Meta's "no
    active session" error for WhatsApp) propagates verbatim so the
    operator sees the real reason. The audit row is only written
    when the adapter call returns successfully.
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)

    cleaned_recipient = _validate_recipient(template.channel, recipient)
    context = _build_context(sample_context)
    rendered_body = resolve(template.body_text, context)
    rendered_subject = resolve(template.subject, context) if template.subject else None

    if template.channel == ConversationChannel.email:
        # Subject is mandatory for email at the schema layer; this is
        # defensive — a template that's somehow missing one falls back
        # to a clear marker so the recipient still knows what arrived.
        subject = rendered_subject or f"[Test] {template.name}"
        channel_message_id = await _dispatch_email(
            recipient=cleaned_recipient,
            subject=subject,
            body=rendered_body,
        )
    elif template.channel == ConversationChannel.whatsapp:
        channel_message_id = await _dispatch_whatsapp(
            session=session,
            org_id=org_id,
            recipient=cleaned_recipient,
            body=rendered_body,
        )
    else:
        raise TestSendNotSupported(channel=template.channel.value)

    audit = MessageTemplateTestSend(
        org_id=org_id,
        template_id=template.id,
        version=template.current_version,
        channel=template.channel,
        sent_to=cleaned_recipient,
        sent_by_user_id=user_id,
        channel_message_id=channel_message_id,
        sent_at=datetime.now(UTC),
    )
    session.add(audit)
    await session.commit()
    await session.refresh(audit)
    logger.info(
        "templates.test_send org=%s template=%s channel=%s recipient=%s channel_message_id=%s",
        org_id,
        template.id,
        template.channel.value,
        cleaned_recipient,
        channel_message_id,
    )
    return audit


__all__ = ["dispatch_test_send"]
