"""External-status sync for the central template library
(``tasks/template-library`` Step 14).

Two public coroutines drive the polish on the external-provider
status story Step 9 started:

* :func:`sync_external_status` — re-queries a single template's
  status from its provider (today: Meta for WhatsApp templates).
  Used by the manual "Refresh status" button and by Step 14's
  hourly Celery sweep.
* :func:`sync_all_pending` — bulk-syncs every ``pending`` or
  ``paused`` template in the org. Per-template failures are logged
  and the loop continues so one rejected WABA doesn't stall the
  rest.

Each successful sync writes a review row with action
``external_sync`` so the editor's review trail surfaces the
"synced from Meta on YYYY-MM-DD" events alongside the operator-
driven submit / approve / reject actions.

When the synced status transitions into ``rejected`` or ``paused``,
:func:`notify_external_status_change` fans the news out to:

* The template's creator (``created_by_user_id``).
* Every user in the org with the ``templates.submit_external``
  permission (Owners + Admins by default; custom roles that have
  been granted the perm are picked up automatically).

The webhook handler at
``core.integrations.whatsapp.templates_service.apply_template_status_update``
ALSO calls :func:`notify_external_status_change` when Meta pushes
us a status update — keeps the two paths emitting the same
notification.

WA is the only channel with a real external review pipeline today
(email / FB Messenger / IG Direct / push have none — Step 13 spec).
Other channels raise :class:`SyncNotSupported`; the SMS-DLT path is
out of scope until an SMS provider lands.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import data_access as templates_da
from src.app.core.templates.exceptions import TemplateError
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateReview,
    TemplateExternalStatus,
    TemplateReviewAction,
)

logger = logging.getLogger(__name__)


class SyncNotSupported(TemplateError):
    """Raised when the channel has no external-provider sync today.
    Email / FB Messenger / IG Direct / push fall here; SMS-DLT will
    when an SMS provider ships."""

    def __init__(self, *, channel: str) -> None:
        super().__init__(f"the {channel!r} channel has no external status to sync")
        self.channel = channel


class MissingExtensionRow(TemplateError):
    """Re-thrown when the WA extension row backing a central WA
    template can't be located. Router maps to 409."""

    def __init__(self, *, channel: str, template_id: uuid.UUID) -> None:
        super().__init__(f"{channel} template {template_id} has no provider extension row")
        self.channel = channel
        self.template_id = template_id


# Meta returns ALL_CAPS strings on ``status``. Same set Step-9's
# webhook handler decodes — we re-map directly to the central enum
# (the WA-extension enum mapping happens inside the webhook handler).
_META_STATUS_TO_EXTERNAL: dict[str, TemplateExternalStatus] = {
    "APPROVED": TemplateExternalStatus.approved,
    "REJECTED": TemplateExternalStatus.rejected,
    "FLAGGED": TemplateExternalStatus.rejected,
    "DISABLED": TemplateExternalStatus.rejected,
    "PAUSED": TemplateExternalStatus.paused,
    "PENDING": TemplateExternalStatus.pending,
    "PENDING_DELETION": TemplateExternalStatus.pending,
    "IN_APPEAL": TemplateExternalStatus.rejected,
}


async def sync_external_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    app_id: str,
    app_secret: str,
) -> MessageTemplate:
    """Refresh ``template_id``'s ``external_status`` against its
    provider. Writes a review row + fires notifications on status
    flips into ``rejected`` / ``paused``.

    Returns the updated central row. Raises
    :class:`TemplateNotFound`, :class:`SyncNotSupported`,
    :class:`MissingExtensionRow`. Meta's
    :class:`MetaGraphError` bubbles up untouched."""
    from src.app.core.templates.service import get_template

    template = await get_template(session, org_id=org_id, template_id=template_id)

    if template.channel != ConversationChannel.whatsapp:
        raise SyncNotSupported(channel=template.channel.value)

    old_status = template.external_status
    new_status, rejection_reason = await _fetch_wa_status(
        session,
        org_id=org_id,
        template=template,
        app_id=app_id,
        app_secret=app_secret,
    )

    if new_status != old_status:
        template.external_status = new_status

    review = MessageTemplateReview(
        org_id=org_id,
        template_id=template.id,
        version=template.current_version,
        reviewer_user_id=user_id,
        action=TemplateReviewAction.external_sync,
        note=_format_sync_note(new_status, rejection_reason),
    )
    session.add(review)
    await session.commit()
    await session.refresh(template)

    logger.info(
        "templates.sync_external org=%s template=%s old=%s new=%s",
        org_id,
        template.id,
        old_status.value,
        new_status.value,
    )

    if new_status != old_status and new_status in (
        TemplateExternalStatus.rejected,
        TemplateExternalStatus.paused,
    ):
        await notify_external_status_change(
            org_id=org_id,
            template=template,
            new_status=new_status,
            rejection_reason=rejection_reason,
        )

    return template


async def sync_all_pending(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    app_id: str,
    app_secret: str,
) -> dict[str, int]:
    """Bulk sync every ``pending`` / ``paused`` template in the org.

    Per-template failures are logged + the loop continues. Returns
    a small dict of ``{checked, updated, failed}`` for the caller
    (Celery task) to surface in worker logs."""
    pending = await templates_da.list_pending_external(session, org_id=org_id)
    checked = 0
    updated = 0
    failed = 0
    for template in pending:
        checked += 1
        before = template.external_status
        try:
            await sync_external_status(
                session,
                org_id=org_id,
                template_id=template.id,
                user_id=None,
                app_id=app_id,
                app_secret=app_secret,
            )
            if template.external_status != before:
                updated += 1
        except SyncNotSupported:
            # Non-WA pending rows can only exist if a future channel
            # adds external review; we skip them quietly so the sweep
            # doesn't generate spam logs once that channel lands.
            continue
        except Exception:
            logger.exception(
                "templates.sync_external failed org=%s template=%s",
                org_id,
                template.id,
            )
            failed += 1
            # Roll back so the next iteration's session is clean.
            await session.rollback()
    return {"checked": checked, "updated": updated, "failed": failed}


# --- helpers -----------------------------------------------------------


async def _fetch_wa_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template: MessageTemplate,
    app_id: str,
    app_secret: str,
) -> tuple[TemplateExternalStatus, str | None]:
    """Resolve the WA extension row, call Meta, return the mapped
    central status + rejection reason. Updates the WA extension's
    own status fields in passing so the legacy
    ``/whatsapp/templates`` page agrees with the central row."""
    from src.app.core.integrations.crypto import decrypt
    from src.app.core.integrations.whatsapp import data_access as wa_da
    from src.app.core.integrations.whatsapp.connect import (
        get_active_config,
    )
    from src.app.core.integrations.whatsapp.meta_graph_client import (
        MetaGraphClient,
    )

    wa_row = await wa_da.get_by_message_template_id(session, template.id)
    if wa_row is None:
        raise MissingExtensionRow(channel=template.channel.value, template_id=template.id)

    if not wa_row.meta_template_id:
        # Never submitted — nothing to sync. Treat as n_a so the
        # operator's "Refresh" click resolves cleanly.
        return TemplateExternalStatus.n_a, None

    bundle = await get_active_config(session)
    if bundle is None or bundle[0].access_token_enc is None:
        raise MissingExtensionRow(channel=template.channel.value, template_id=template.id)

    integration, config = bundle
    token = decrypt(integration.access_token_enc)
    client = MetaGraphClient(
        api_version=config.api_version,
        app_id=app_id,
        app_secret=app_secret,
    )
    meta_body = await client.get_message_template(
        token=token, meta_template_id=wa_row.meta_template_id
    )

    raw_status = str(meta_body.get("status") or "").upper()
    mapped = _META_STATUS_TO_EXTERNAL.get(raw_status)
    if mapped is None:
        logger.warning(
            "templates.sync unknown_meta_status org=%s template=%s status=%s",
            org_id,
            template.id,
            raw_status,
        )
        # Unknown → leave the central row as-is. Returning the current
        # status here keeps the no-change branch clean upstream.
        return template.external_status, wa_row.rejection_reason

    rejection_reason = meta_body.get("rejected_reason")
    if isinstance(rejection_reason, str):
        rejection_reason = rejection_reason.strip() or None
    else:
        rejection_reason = None

    # Mirror the webhook handler's writeback so legacy WA management
    # surfaces don't lag the central row.
    wa_row.status = raw_status
    if mapped == TemplateExternalStatus.rejected:
        wa_row.rejection_reason = rejection_reason or wa_row.rejection_reason
    elif mapped == TemplateExternalStatus.approved:
        wa_row.rejection_reason = None
    wa_row.last_synced_at = datetime.now(UTC)

    return mapped, rejection_reason


def _format_sync_note(
    status: TemplateExternalStatus,
    rejection_reason: str | None,
) -> str:
    """Compact human-readable summary stored on the review row's
    ``note`` field — the editor's review-trail UI surfaces it under
    the action chip."""
    base = f"Meta reports status='{status.value}'"
    if rejection_reason:
        return f"{base}; reason: {rejection_reason}"
    return base


# --- notification fan-out ----------------------------------------------


async def notify_external_status_change(
    *,
    org_id: uuid.UUID,
    template: MessageTemplate,
    new_status: TemplateExternalStatus,
    rejection_reason: str | None,
) -> None:
    """Fan a notification out to every recipient who should know
    that ``template`` was just rejected / paused by the provider.

    Recipients:
      * The template's creator (``created_by_user_id``).
      * Every user in the org with the ``templates.submit_external``
        permission resolved via the active role assignment.

    Best-effort — :func:`core.notifications.service.notify` is
    non-raising so a slow socket or missing preference row never
    fails the calling transaction."""
    if new_status not in (
        TemplateExternalStatus.rejected,
        TemplateExternalStatus.paused,
    ):
        return

    from src.app.core.notifications.service import notify

    recipients = await _resolve_notification_recipients(org_id, template)
    if not recipients:
        return

    status_label = "rejected" if new_status == TemplateExternalStatus.rejected else "paused"
    title = f"Template '{template.name}' was {status_label} by Meta"
    body = rejection_reason or (
        "No reason supplied by Meta. Open the template to review + resubmit."
    )
    payload = {
        "template_id": str(template.id),
        "channel": template.channel.value,
        "external_status": new_status.value,
        "rejection_reason": rejection_reason,
    }

    for recipient_id in recipients:
        await notify(
            org_id=org_id,
            user_id=recipient_id,
            type="templates.external_status_changed",
            title=title,
            body=body,
            payload=payload,
        )

    # Audit event so a future digest builder (Step 14 risks: "if 50
    # templates rejected at once, batch into a digest") can roll up
    # repeated emits without touching the notify path.
    logger.info(
        "templates.notify_external_status org=%s template=%s status=%s recipients=%d",
        org_id,
        template.id,
        new_status.value,
        len(recipients),
    )


async def _resolve_notification_recipients(
    org_id: uuid.UUID, template: MessageTemplate
) -> list[uuid.UUID]:
    """Return the deduped list of legacy-UUID user ids who should
    receive the notification. Uses its own session so the call can
    happen post-commit without contending with the caller's
    transaction (mirroring ``audit.log`` / ``notifications.notify``
    patterns)."""
    from src.app.shared.db import async_session

    recipient_set: set[uuid.UUID] = set()
    if template.created_by_user_id:
        recipient_set.add(template.created_by_user_id)

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                    SELECT DISTINCT ul.legacy_uuid
                    FROM tbl_organization_members om
                    JOIN tbl_user_login ul ON ul.id = om.user_member_id
                    JOIN tbl_role_permissions rp ON rp.role_id = om.role_id
                    JOIN tbl_permissions p ON p.id = rp.permission_id
                    WHERE om.organization_id = :org_id
                      AND om.is_active = TRUE
                      AND om.status = 'active'
                      AND ul.legacy_uuid IS NOT NULL
                      AND p.key = 'templates.submit_external'
                    """
                    ),
                    {"org_id": str(org_id)},
                )
            )
            .mappings()
            .all()
        )
    for row in rows:
        recipient_set.add(row["legacy_uuid"])
    return list(recipient_set)


async def prepare_resubmit(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> MessageTemplate:
    """Step 14 — "Resubmit" affordance for templates Meta rejected.

    Flips the central row back to ``internal_status='draft'`` +
    ``external_status='n_a'`` so the operator can fix the body and
    submit again. Writes a review row of action=``external_sync``
    with a ``"resubmit prepared"`` note so the trail shows the
    operator-initiated reset.

    Only valid when the template's current ``external_status`` is
    ``rejected``. Other states raise :class:`TemplateError` and the
    router maps to 409 — protects against accidental clicks that
    would wipe a real provider verdict."""
    from src.app.core.templates.models import TemplateInternalStatus
    from src.app.core.templates.service import get_template

    template = await get_template(session, org_id=org_id, template_id=template_id)

    if template.external_status != TemplateExternalStatus.rejected:
        raise TemplateError("resubmit is only available on rejected templates")

    template.internal_status = TemplateInternalStatus.draft
    template.external_status = TemplateExternalStatus.n_a

    review = MessageTemplateReview(
        org_id=org_id,
        template_id=template.id,
        version=template.current_version,
        reviewer_user_id=user_id,
        action=TemplateReviewAction.external_sync,
        note="resubmit prepared — operator cleared rejection",
    )
    session.add(review)
    await session.commit()
    await session.refresh(template)
    logger.info(
        "templates.resubmit_prepared org=%s template=%s",
        org_id,
        template.id,
    )
    return template


__all__ = [
    "MissingExtensionRow",
    "SyncNotSupported",
    "notify_external_status_change",
    "prepare_resubmit",
    "sync_all_pending",
    "sync_external_status",
]
