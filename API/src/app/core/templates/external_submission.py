"""Channel-dispatched external-submission helper for the central
template library.

Today the only provider with a real external review pipeline is
WhatsApp (Meta). SMS-DLT is wired in Step 12; the other channels
(email / FB Messenger / IG Direct / push) have no external review
and raise :class:`ExternalSubmissionNotSupported`.

The router endpoint ``POST /api/v1/templates/{id}/submit-external``
calls into :func:`submit_external` here; the WA branch resolves the
matching ``tbl_whatsapp_templates`` extension row via the new
``message_template_id`` link from Step 9, then forwards to
``core.integrations.whatsapp.templates_service.submit_for_approval``
which talks to Meta and updates both the WA row's status AND the
central row's ``external_status``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.integrations.whatsapp import data_access as wa_da
from src.app.core.templates.exceptions import (
    TemplateError,
)
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateExternalStatus,
)
from src.app.core.templates.service import get_template

logger = logging.getLogger(__name__)


class ExternalSubmissionNotSupported(TemplateError):
    """Raised when the channel has no external-review pipeline (email,
    FB Messenger, IG Direct, push). Router maps to 422."""

    def __init__(self, *, channel: str) -> None:
        super().__init__(
            f"the {channel!r} channel has no external provider review; "
            "templates flip to published once internal review approves"
        )
        self.channel = channel


class MissingExtensionRow(TemplateError):
    """Raised when a WA template's central row exists but the matching
    ``tbl_whatsapp_templates`` extension row can't be found. Indicates
    the template was created outside Step-9's bridge (or was deleted
    on the WA side). Router maps to 409 with an operator-actionable
    message."""

    def __init__(self, *, channel: str, template_id: uuid.UUID) -> None:
        super().__init__(
            f"{channel} template {template_id} has no provider extension "
            "row; create the WA template via Settings → WhatsApp → "
            "Templates first"
        )
        self.channel = channel
        self.template_id = template_id


async def submit_external(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    app_id: str,
    app_secret: str,
) -> MessageTemplate:
    """Submit the template to its channel's external review pipeline.

    Returns the updated central row with ``external_status='pending'``
    on success. Raises :class:`ExternalSubmissionNotSupported` for
    channels without a provider review.

    The ``app_id`` + ``app_secret`` args are Meta-App credentials
    needed by the WA submission path; the router pulls them from the
    SOPS-managed config and passes them in.
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)

    if template.channel != ConversationChannel.whatsapp:
        raise ExternalSubmissionNotSupported(channel=template.channel.value)

    # Resolve the WA extension row via the Step-9 reciprocal link.
    wa_row = await wa_da.get_by_message_template_id(session, template.id)
    if wa_row is None:
        raise MissingExtensionRow(channel=template.channel.value, template_id=template.id)

    # Delegate to the existing WA submission service. It talks to
    # Meta, updates the WA row's submission_status, and the
    # status_update webhook later syncs both rows. We also flip the
    # central row's external_status to 'pending' here so the operator
    # sees instant feedback without waiting for the webhook.
    from src.app.core.integrations.whatsapp.templates_service import (
        submit_for_approval,
    )

    await submit_for_approval(
        session,
        actor_id=user_id or uuid.uuid4(),
        template_id=wa_row.id,
        app_id=app_id,
        app_secret=app_secret,
    )

    template.external_status = TemplateExternalStatus.pending
    await session.commit()
    await session.refresh(template)
    logger.info(
        "templates.external_submit org=%s template=%s wa_template=%s",
        org_id,
        template.id,
        wa_row.id,
    )
    return template


async def get_external_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> dict:
    """Return the current external-status payload for the editor's
    status badge. For WA: pulls the rejection reason + last sync time
    from the extension row. For other channels: returns the central
    row's ``external_status`` only (no extra metadata)."""
    template = await get_template(session, org_id=org_id, template_id=template_id)
    payload = {
        "status": template.external_status.value,
        "rejection_reason": None,
        "last_synced_at": None,
    }
    if template.channel == ConversationChannel.whatsapp:
        wa_row = await wa_da.get_by_message_template_id(session, template.id)
        if wa_row is not None:
            payload["rejection_reason"] = wa_row.rejection_reason
            payload["last_synced_at"] = (
                wa_row.last_synced_at.isoformat() if wa_row.last_synced_at else None
            )
    return payload


__all__ = [
    "ExternalSubmissionNotSupported",
    "MissingExtensionRow",
    "get_external_status",
    "submit_external",
]
