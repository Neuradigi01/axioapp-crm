"""Service layer for WhatsApp template management
(whatsapp-platform-upgrade Step 8).

Owns the CRUD lifecycle the Step 7 work didn't cover:

* ``create_draft`` — operator-authored template, ``submission_status='draft'``.
* ``update_draft`` — edit allowed only while ``draft`` or ``rejected``.
* ``duplicate`` — clone any row into a fresh draft, name suffixed with
  ``"_copy"`` so Meta's name uniqueness rule holds.
* ``submit_for_approval`` — POST to Meta's
  ``/{waba_id}/message_templates`` endpoint, persist the returned
  ``meta_template_id``, flip ``submission_status='pending_review'``.
* ``delete_template`` — local delete; if the row was previously
  submitted (has ``meta_template_id``), also calls Meta's DELETE.
* ``apply_template_status_update`` — webhook entry-point. Used by the
  WhatsApp webhook router when Meta sends
  ``field='message_template_status_update'``. Translates Meta's
  ``event`` string to our enum + persists ``rejection_reason``.

The read-side ``list_templates`` from the legacy module stays the
campaign picker's API (unchanged); a Step-8-aware ``list`` lives in
``templates_router`` that also exposes the new fields.

All writes RLS-scope via the existing ``TenantScoped`` mixin — the
router sets ``RequestContext.org_id`` from the JWT before calling in.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.meta_graph_client import (
    HttpClientFactory,
    MetaGraphClient,
    MetaGraphError,
)
from src.app.core.integrations.whatsapp.models import (
    WhatsAppTemplate,
    WhatsAppTemplateSubmissionStatus,
)
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppTemplateUpsert,
)

logger = logging.getLogger(__name__)

_VARIABLE_RE = re.compile(r"\{\{(\d+)\}\}")

# Mapping from Meta's webhook event names to our enum. Meta uses
# ALL_CAPS in the webhook (`APPROVED`, `REJECTED`, …); we store lower-
# snake-case. Unknown event strings are ignored — the audit log
# records the raw event for forensic follow-up.
_META_EVENT_TO_STATUS = {
    "APPROVED": WhatsAppTemplateSubmissionStatus.approved,
    "REJECTED": WhatsAppTemplateSubmissionStatus.rejected,
    "FLAGGED": WhatsAppTemplateSubmissionStatus.rejected,
    "PAUSED": WhatsAppTemplateSubmissionStatus.paused,
    "DISABLED": WhatsAppTemplateSubmissionStatus.disabled,
    "PENDING": WhatsAppTemplateSubmissionStatus.pending_review,
    "PENDING_DELETION": WhatsAppTemplateSubmissionStatus.pending_review,
    "IN_APPEAL": WhatsAppTemplateSubmissionStatus.rejected,
}

_EDITABLE_STATUSES = {
    WhatsAppTemplateSubmissionStatus.draft,
    WhatsAppTemplateSubmissionStatus.rejected,
}


# tasks/template-library Step 9 — mirror of `_META_EVENT_TO_STATUS`
# but mapping the WA submission_status into the central
# `tbl_message_templates.external_status` value. Used by
# `apply_template_status_update` to keep the central row in sync.
def _build_central_external_map():
    from src.app.core.templates.models import TemplateExternalStatus

    return {
        WhatsAppTemplateSubmissionStatus.approved: TemplateExternalStatus.approved,
        WhatsAppTemplateSubmissionStatus.rejected: TemplateExternalStatus.rejected,
        WhatsAppTemplateSubmissionStatus.paused: TemplateExternalStatus.paused,
        WhatsAppTemplateSubmissionStatus.disabled: TemplateExternalStatus.rejected,
        WhatsAppTemplateSubmissionStatus.pending_review: TemplateExternalStatus.pending,
        WhatsAppTemplateSubmissionStatus.draft: TemplateExternalStatus.n_a,
    }


_WA_STATUS_TO_CENTRAL_EXTERNAL = _build_central_external_map()


# --- helpers --------------------------------------------------------------


def _count_variables(body: str) -> int:
    """Count distinct ``{{n}}`` placeholders — same regex the legacy
    sync uses, kept consistent so the picker's count agrees with
    every persistence path."""
    return len({int(m) for m in _VARIABLE_RE.findall(body)})


def _payload_to_components(
    payload: WhatsAppTemplateUpsert,
) -> list[dict[str, Any]]:
    """Build Meta's ``components[]`` array from the validated upsert
    payload. Mirrored on every create/update + replayed verbatim at
    submit time so what the operator approved on the form is exactly
    what Meta receives."""
    components: list[dict[str, Any]] = []

    if payload.header_type == "TEXT":
        components.append(
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": payload.header_text,
            }
        )
    elif payload.header_type in ("IMAGE", "VIDEO", "DOCUMENT"):
        # Sample asset attaches at submit-time via `example.header_handle`
        # — out of scope for the management surface, the operator will
        # see Meta's rejection if they forget to wire it.
        components.append({"type": "HEADER", "format": payload.header_type})

    components.append({"type": "BODY", "text": payload.body})

    if payload.footer_text:
        components.append({"type": "FOOTER", "text": payload.footer_text})

    if payload.buttons:
        buttons_payload: list[dict[str, Any]] = []
        for b in payload.buttons:
            entry: dict[str, Any] = {"type": b.type, "text": b.text}
            if b.url:
                entry["url"] = b.url
            if b.phone_number:
                entry["phone_number"] = b.phone_number
            buttons_payload.append(entry)
        components.append({"type": "BUTTONS", "buttons": buttons_payload})

    return components


def _components_from_record(row: WhatsAppTemplate) -> list[dict[str, Any]]:
    """Reconstruct ``components[]`` for a submit call from whichever
    representation is populated. ``body_components`` is preferred (it's
    what the operator built); the legacy ``body / header_* / footer_*``
    columns are the fallback for old sync rows that haven't been
    re-built yet."""
    if isinstance(row.body_components, list) and row.body_components:
        return list(row.body_components)

    components: list[dict[str, Any]] = []
    if row.header_type == "TEXT" and row.header_text:
        components.append(
            {"type": "HEADER", "format": "TEXT", "text": row.header_text}
        )
    elif row.header_type in ("IMAGE", "VIDEO", "DOCUMENT"):
        components.append({"type": "HEADER", "format": row.header_type})
    components.append({"type": "BODY", "text": row.body})
    if row.footer_text:
        components.append({"type": "FOOTER", "text": row.footer_text})
    return components


async def _resolve_active_bundle(session: AsyncSession):
    """Fetch the active org's integration + config OR raise 409 — same
    shape used by send / sync paths so error messages stay consistent."""
    bundle = await get_active_config(session)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. "
            "Connect it in Settings → Integrations."
        )
    return bundle


# --- reads ----------------------------------------------------------------


async def list_templates_managed(
    session: AsyncSession,
    *,
    submission_status: Optional[
        WhatsAppTemplateSubmissionStatus
    ] = None,
    category: Optional[str] = None,
    language: Optional[str] = None,
) -> list[WhatsAppTemplate]:
    """Step-8 listing — includes drafts and all lifecycle states.

    Unlike the legacy ``list_templates`` (which the campaign picker
    uses and only wants Meta-approved rows), this returns every row
    the management surface needs to render. RLS auto-scopes to the
    active org."""
    stmt = select(WhatsAppTemplate).order_by(
        WhatsAppTemplate.category, WhatsAppTemplate.name
    )
    if submission_status is not None:
        stmt = stmt.where(
            WhatsAppTemplate.submission_status == submission_status
        )
    if category is not None:
        stmt = stmt.where(WhatsAppTemplate.category == category)
    if language is not None:
        stmt = stmt.where(WhatsAppTemplate.language == language)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def get_template_or_404(
    session: AsyncSession, template_id: uuid.UUID
) -> WhatsAppTemplate:
    row = (
        await session.execute(
            select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp template not found.",
        )
    return row


# --- writes ---------------------------------------------------------------


async def create_draft(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    payload: WhatsAppTemplateUpsert,
) -> WhatsAppTemplate:
    """Create a new draft. Meta is NOT called — submission happens via
    the dedicated endpoint when the operator is ready.

    Name uniqueness inside the org is enforced here (Meta enforces it
    on submit, but we catch it earlier so the operator doesn't waste
    a Meta round-trip)."""
    integration, _ = await _resolve_active_bundle(session)

    existing = (
        await session.execute(
            select(WhatsAppTemplate)
            .where(WhatsAppTemplate.integration_id == integration.id)
            .where(WhatsAppTemplate.name == payload.name)
            .where(WhatsAppTemplate.language == payload.language)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A template named '{payload.name}' "
                f"({payload.language}) already exists."
            ),
        )

    components = _payload_to_components(payload)
    row = WhatsAppTemplate(
        org_id=integration.org_id,
        integration_id=integration.id,
        name=payload.name,
        language=payload.language,
        category=payload.category,
        # Mirror the operator-side enum into Meta's `status` text so
        # existing campaign-picker filters (which read `status`) see
        # 'DRAFT' until submission lands the approved status.
        status="DRAFT",
        body=payload.body,
        header_type=payload.header_type,
        header_text=payload.header_text,
        footer_text=payload.footer_text,
        variable_count=_count_variables(payload.body),
        body_components=components,
        submission_status=WhatsAppTemplateSubmissionStatus.draft,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.whatsapp.template_created",
        entity_type="whatsapp_template",
        entity_id=row.id,
        user_id=actor_id,
        after={
            "name": row.name,
            "language": row.language,
            "category": row.category,
        },
    )
    return row


async def update_draft(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: WhatsAppTemplateUpsert,
) -> WhatsAppTemplate:
    """Edit an existing draft / rejected row. Approved or
    pending-review rows refuse the edit with 403 — Meta does not let
    operators rewrite an approved template, only re-submit a new one."""
    row = await get_template_or_404(session, template_id)
    if row.submission_status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Templates in '{row.submission_status.value}' state "
                "cannot be edited. Duplicate it to make changes."
            ),
        )

    before = {
        "name": row.name,
        "language": row.language,
        "category": row.category,
        "body": row.body,
        "header_type": row.header_type,
        "footer_text": row.footer_text,
    }
    row.name = payload.name
    row.language = payload.language
    row.category = payload.category
    row.body = payload.body
    row.header_type = payload.header_type
    row.header_text = payload.header_text
    row.footer_text = payload.footer_text
    row.variable_count = _count_variables(payload.body)
    row.body_components = _payload_to_components(payload)
    # If the operator edited after a rejection, drop back to draft so
    # they have to explicitly re-submit (matches Meta's flow — a
    # rejected template's edit doesn't auto-resubmit).
    if row.submission_status == WhatsAppTemplateSubmissionStatus.rejected:
        row.submission_status = WhatsAppTemplateSubmissionStatus.draft
        row.rejection_reason = None
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.whatsapp.template_updated",
        entity_type="whatsapp_template",
        entity_id=row.id,
        user_id=actor_id,
        before=before,
        after={
            "name": row.name,
            "language": row.language,
            "category": row.category,
            "body": row.body,
            "header_type": row.header_type,
            "footer_text": row.footer_text,
        },
    )
    return row


async def duplicate_template(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    template_id: uuid.UUID,
) -> WhatsAppTemplate:
    """Clone any row into a new draft, name suffixed with ``_copy`` so
    Meta's name uniqueness rule holds. Suffix collision (e.g. running
    duplicate twice) appends ``_copy_2``, ``_copy_3``, etc."""
    src = await get_template_or_404(session, template_id)
    new_name = await _allocate_copy_name(
        session, integration_id=src.integration_id, base=src.name,
        language=src.language,
    )
    components = (
        list(src.body_components) if isinstance(src.body_components, list)
        else _components_from_record(src)
    )
    row = WhatsAppTemplate(
        org_id=src.org_id,
        integration_id=src.integration_id,
        name=new_name,
        language=src.language,
        category=src.category,
        status="DRAFT",
        body=src.body,
        header_type=src.header_type,
        header_text=src.header_text,
        footer_text=src.footer_text,
        variable_count=src.variable_count,
        body_components=components,
        submission_status=WhatsAppTemplateSubmissionStatus.draft,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.whatsapp.template_duplicated",
        entity_type="whatsapp_template",
        entity_id=row.id,
        user_id=actor_id,
        after={"source_id": str(src.id), "name": row.name},
    )
    return row


async def _allocate_copy_name(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    base: str,
    language: str,
) -> str:
    """Find an unused ``{base}_copy`` / ``{base}_copy_2`` name in this
    integration. Meta enforces lowercase + underscores so ``_copy`` is
    the safe suffix shape."""
    for suffix in ("_copy", *(f"_copy_{i}" for i in range(2, 100))):
        candidate = f"{base}{suffix}"
        exists = (
            await session.execute(
                select(WhatsAppTemplate.id)
                .where(WhatsAppTemplate.integration_id == integration_id)
                .where(WhatsAppTemplate.name == candidate)
                .where(WhatsAppTemplate.language == language)
            )
        ).scalar_one_or_none()
        if exists is None:
            return candidate
    # 100 copies is a clear sign of a script gone wrong — refuse rather
    # than allocate a 101st.
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Too many duplicates of this template — clean up before retrying.",
    )


async def submit_for_approval(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    template_id: uuid.UUID,
    app_id: str,
    app_secret: str,
    http_client_factory: Optional[HttpClientFactory] = None,
) -> WhatsAppTemplate:
    """POST the draft to Meta's ``/{waba_id}/message_templates``.

    Refuses anything not in draft / rejected. On Meta success the row
    flips to ``pending_review`` and ``meta_template_id`` lands. On
    Meta 4xx the row stays draft and the error message bubbles to
    the operator verbatim — Meta's reasons are operator-actionable
    (e.g. "Header text too long")."""
    row = await get_template_or_404(session, template_id)
    if row.submission_status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Template is already in state "
                f"'{row.submission_status.value}' — nothing to submit."
            ),
        )

    integration, config = await _resolve_active_bundle(session)
    if integration.access_token_enc is None:
        raise WhatsAppNotConnected(
            "Stored credentials are missing; reconnect required."
        )
    token = decrypt(integration.access_token_enc)

    client_kwargs: dict[str, Any] = {
        "api_version": config.api_version,
        "app_id": app_id,
        "app_secret": app_secret,
    }
    if http_client_factory is not None:
        client_kwargs["http_client_factory"] = http_client_factory
    client = MetaGraphClient(**client_kwargs)

    components = _components_from_record(row)
    try:
        meta_body = await client.submit_template(
            waba_id=config.waba_id,
            token=token,
            name=row.name,
            language=row.language,
            category=row.category,
            components=components,
        )
    except MetaGraphError as exc:
        await audit.log(
            "integration.whatsapp.template_submit_failed",
            entity_type="whatsapp_template",
            entity_id=row.id,
            user_id=actor_id,
            after={
                "meta_code": exc.meta_code,
                "message": exc.user_message,
            },
        )
        raise HTTPException(
            status_code=exc.http_status, detail=exc.user_message
        )

    meta_template_id = (
        str(meta_body.get("id")) if meta_body.get("id") is not None else None
    )
    meta_status = (
        str(meta_body.get("status")) if meta_body.get("status") else "PENDING"
    )

    row.meta_template_id = meta_template_id
    row.status = meta_status
    row.submission_status = WhatsAppTemplateSubmissionStatus.pending_review
    row.submitted_by_user_id = actor_id
    row.submitted_at = datetime.now(timezone.utc)
    row.rejection_reason = None
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.whatsapp.template_submitted",
        entity_type="whatsapp_template",
        entity_id=row.id,
        user_id=actor_id,
        after={
            "meta_template_id": meta_template_id,
            "meta_status": meta_status,
        },
    )
    return row


async def delete_template(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    template_id: uuid.UUID,
    app_id: str,
    app_secret: str,
    http_client_factory: Optional[HttpClientFactory] = None,
) -> None:
    """Local + Meta delete.

    Rows without ``meta_template_id`` are pure-local and delete with no
    Meta call. Rows that have been submitted go to Meta first so the
    template disappears from the WABA. Meta delete is idempotent (Meta
    returns success if already gone); we propagate the failure if Meta
    rejects (e.g. 403 from a token without ``whatsapp_business_management``
    scope)."""
    row = await get_template_or_404(session, template_id)

    if row.meta_template_id:
        integration, config = await _resolve_active_bundle(session)
        if integration.access_token_enc is None:
            raise WhatsAppNotConnected(
                "Stored credentials are missing; reconnect required."
            )
        token = decrypt(integration.access_token_enc)
        client_kwargs: dict[str, Any] = {
            "api_version": config.api_version,
            "app_id": app_id,
            "app_secret": app_secret,
        }
        if http_client_factory is not None:
            client_kwargs["http_client_factory"] = http_client_factory
        client = MetaGraphClient(**client_kwargs)
        try:
            await client.delete_template(
                waba_id=config.waba_id,
                token=token,
                name=row.name,
                meta_template_id=row.meta_template_id,
            )
        except MetaGraphError as exc:
            raise HTTPException(
                status_code=exc.http_status, detail=exc.user_message
            )

    snapshot = {
        "name": row.name,
        "language": row.language,
        "category": row.category,
        "meta_template_id": row.meta_template_id,
    }
    await session.delete(row)
    await session.commit()

    await audit.log(
        "integration.whatsapp.template_deleted",
        entity_type="whatsapp_template",
        entity_id=template_id,
        user_id=actor_id,
        before=snapshot,
    )


# --- webhook --------------------------------------------------------------


async def apply_template_status_update(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    meta_template_id: Optional[str],
    template_name: Optional[str],
    language: Optional[str],
    event: str,
    reason: Optional[str],
) -> bool:
    """Apply a ``message_template_status_update`` webhook event to the
    matching local row.

    Lookup priority: ``meta_template_id`` (when Meta sent it),
    falling back to the ``(name, language)`` pair. Returns True if a
    row was updated, False when no match was found (silent no-op —
    Meta sometimes replays for templates we don't track)."""
    row: Optional[WhatsAppTemplate] = None
    if meta_template_id:
        row = (
            await session.execute(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.meta_template_id == meta_template_id,
                    WhatsAppTemplate.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
    if row is None and template_name and language:
        row = (
            await session.execute(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.name == template_name,
                    WhatsAppTemplate.language == language,
                    WhatsAppTemplate.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        logger.info(
            "template_status_update no match: event=%s meta_id=%s name=%s",
            event,
            meta_template_id,
            template_name,
        )
        return False

    new_status = _META_EVENT_TO_STATUS.get(event.upper())
    if new_status is None:
        logger.warning("unknown template status event: %s", event)
        return False

    before_status = row.submission_status
    row.submission_status = new_status
    # Mirror Meta's text for legacy callers reading `status`.
    row.status = event.upper()
    if new_status == WhatsAppTemplateSubmissionStatus.rejected:
        row.rejection_reason = reason or row.rejection_reason
    elif new_status == WhatsAppTemplateSubmissionStatus.approved:
        # Cleared on approval so a re-approved row doesn't carry stale
        # text from a previous rejection.
        row.rejection_reason = None
    if meta_template_id and not row.meta_template_id:
        # Backfill — Meta sent us an id we hadn't recorded yet (e.g.
        # the submit response was lost in transit).
        row.meta_template_id = meta_template_id
    row.last_synced_at = datetime.now(timezone.utc)

    # tasks/template-library Step 9 — also sync the central
    # `tbl_message_templates.external_status` so the unified library's
    # editor + list show the live Meta verdict without an extra call.
    # Lookup priority: the reciprocal `message_template_id` link
    # (preferred — set by migration 0120 + by new-template create);
    # falls back to `external_provider_id == meta_template_id` for any
    # extension row whose link wasn't backfilled yet.
    central_external = _WA_STATUS_TO_CENTRAL_EXTERNAL.get(new_status)
    if central_external is not None:
        from src.app.core.templates.models import MessageTemplate

        central_row: Optional[MessageTemplate] = None
        if row.message_template_id:
            central_row = (
                await session.execute(
                    select(MessageTemplate).where(
                        MessageTemplate.id == row.message_template_id,
                        MessageTemplate.org_id == org_id,
                    )
                )
            ).scalar_one_or_none()
        if central_row is None and row.meta_template_id:
            central_row = (
                await session.execute(
                    select(MessageTemplate).where(
                        MessageTemplate.external_provider_id == row.meta_template_id,
                        MessageTemplate.org_id == org_id,
                    )
                )
            ).scalar_one_or_none()
        if central_row is not None:
            central_row.external_status = central_external

    await session.commit()

    await audit.log(
        "integration.whatsapp.template_status_synced",
        entity_type="whatsapp_template",
        entity_id=row.id,
        before={"submission_status": before_status.value},
        after={
            "submission_status": new_status.value,
            "event": event,
            "reason": reason,
        },
    )
    return True


__all__ = [
    "apply_template_status_update",
    "create_draft",
    "delete_template",
    "duplicate_template",
    "get_template_or_404",
    "list_templates_managed",
    "submit_for_approval",
    "update_draft",
]
