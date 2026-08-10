"""Service layer for the central template library.

CRUD + version creation. The router (Step 3) is a thin shell over
these functions; future automation + workflow dispatchers will also
call into ``get_template`` / ``list_templates`` to render outbound
sends.

Every write happens inside a single async transaction:

  * :func:`create_template` inserts both the parent template row and
    its initial ``version=1`` row atomically. The functional unique
    index on ``(org_id, lower(name), channel)`` (migration 0117) is
    the source of truth for "no duplicate name per channel per org" —
    the service catches the ``IntegrityError`` and surfaces a
    :class:`DuplicateTemplateName` so the router can return a
    structured 409.
  * :func:`update_template` writes a new ``MessageTemplateVersion``
    row, bumps the parent's ``current_version``, and updates the
    parent's mutable columns. Rejects with :class:`TemplateLocked`
    when the parent isn't in ``draft`` — Step 4's workflow moves
    non-draft templates back to draft via reject / request_changes.
  * :func:`archive_template` flips ``internal_status='archived'`` and
    is idempotent.

Read paths (``get_template`` / ``list_templates`` /
``list_versions`` / ``get_version``) lean on the global RLS hook
(``do_orm_execute`` in :mod:`src.app.shared.orm`) to scope queries
to the current org. Tests + production callers must set a
:class:`RequestContext` before invoking these — without it the ORM
filter is skipped, but Postgres RLS still denies non-matching rows
at the engine level.

The audit story (which rows changed, who changed them) lives in
Step 4 alongside the workflow transitions — the review trail
naturally records every state-machine action. This step writes the
content, Step 4 records who blessed it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import data_access
from src.app.core.templates.exceptions import (
    DuplicateTemplateName,
    TemplateLocked,
    TemplateNotFound,
)
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.sanitizer import derive_plain_text, sanitize_email_html
from src.app.core.templates.schemas import TemplateCreate, TemplateUpdate
from src.app.core.templates.variables import (
    extract_variable_paths,
    reject_jinja_statements,
)

logger = logging.getLogger(__name__)


_EDIT_LOCKED_STATUSES = frozenset(
    {
        TemplateInternalStatus.in_review,
        TemplateInternalStatus.approved,
        TemplateInternalStatus.published,
    }
)


# --- reads --------------------------------------------------------------
#
# Reads delegate to ``core.templates.data_access`` — the service-layer
# wrappers add the "raise TemplateNotFound on None" + the cross-tenant
# guard (loading the parent template before its versions). Pure DAL
# queries stay in ``data_access/`` per the project convention.


async def get_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> MessageTemplate:
    """Return the template row or raise :class:`TemplateNotFound`."""
    row = await data_access.get_template(session, org_id=org_id, template_id=template_id)
    if row is None:
        raise TemplateNotFound(str(template_id))
    return row


async def find_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> MessageTemplate | None:
    """Non-raising public lookup. Returns None on miss — callers
    (campaigns / automation) that want their own error message use
    this instead of :func:`get_template`."""
    return await data_access.get_template(session, org_id=org_id, template_id=template_id)


async def list_templates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: ConversationChannel | None = None,
    internal_status: TemplateInternalStatus | None = None,
    external_status: TemplateExternalStatus | None = None,
    is_active: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[MessageTemplate, str | None]], int]:
    """Filterable + paginated list. Returns ``(rows, total)`` where each
    row is ``(MessageTemplate, external_rejection_reason)`` — the reason
    is the WhatsApp extension's rejection text (Step 02 of
    ``tasks/campaigns-page-update``); ``None`` for non-WA rows or
    unrejected WA rows."""
    return await data_access.list_templates(
        session,
        org_id=org_id,
        channel=channel,
        internal_status=internal_status,
        external_status=external_status,
        is_active=is_active,
        q=q,
        limit=limit,
        offset=offset,
    )


async def list_versions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[MessageTemplateVersion]:
    """Return version rows for a template, newest first. Raises
    :class:`TemplateNotFound` when the template doesn't belong to
    this org (defends against fishing for other-org template ids)."""
    await get_template(session, org_id=org_id, template_id=template_id)
    return await data_access.list_versions(
        session, template_id=template_id, limit=limit, offset=offset
    )


async def get_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    version: int,
) -> MessageTemplateVersion:
    """Return one specific past version. Raises
    :class:`TemplateNotFound` if either the template or the version
    is absent — clients shouldn't be able to distinguish the two
    failure modes."""
    await get_template(session, org_id=org_id, template_id=template_id)
    row = await data_access.get_version(session, template_id=template_id, version=version)
    if row is None:
        raise TemplateNotFound(f"{template_id} v{version}")
    return row


# --- writes -------------------------------------------------------------


def _resolve_body_text(
    *,
    provided_text: str | None,
    body_html: str | None,
    fallback_auto: bool,
) -> str:
    """Pick the ``body_text`` that lands on the row.

    Returns the operator's explicit text when they supplied it. Falls
    back to the plain-text derivation of ``body_html`` when the operator
    left ``body_text`` empty and enabled ``body_text_fallback_auto``.
    Returns the empty string otherwise — the schema validator has
    already rejected the "neither supplied" case, so this branch only
    fires when the operator explicitly wanted an HTML-only template
    with fallback disabled (rare, but supported).
    """
    if provided_text and provided_text.strip():
        return provided_text
    if body_html and fallback_auto:
        return derive_plain_text(body_html)
    return provided_text or ""


async def _upsert_wa_extension(
    session: AsyncSession,
    *,
    template: MessageTemplate,
    payload: Any,
) -> None:
    """Persist WA-specific fields onto the ``tbl_whatsapp_templates``
    extension row that shadows this central template.

    Requires the org to have connected a WhatsApp integration — the
    extension row is FK'd to ``tbl_integrations``. When no integration
    exists we return silently so the operator can still author the WA
    fields; they'll materialise on the next Meta-submit round once the
    integration lands. Idempotent per ``message_template_id``: existing
    rows are patched in place, missing rows are inserted.
    """
    from sqlalchemy import select as _select

    from src.app.core.integrations.models import Integration, IntegrationProvider
    from src.app.core.integrations.whatsapp.models import (
        WhatsAppTemplate,
        WhatsAppTemplateSubmissionStatus,
    )

    integration = (
        await session.execute(
            _select(Integration).where(Integration.provider == IntegrationProvider.whatsapp)
        )
    ).scalar_one_or_none()
    if integration is None:
        logger.info(
            "wa extension skipped for template %s — org has no WhatsApp integration",
            template.id,
        )
        return

    # Build Meta component payload from the structured fields so
    # ``external_submission`` can re-send verbatim.
    components: list[dict[str, Any]] = [
        {"type": "BODY", "text": template.body_text},
    ]
    if payload.header_type and payload.header_text:
        components.insert(
            0,
            {
                "type": "HEADER",
                "format": payload.header_type.upper(),
                "text": payload.header_text if payload.header_type == "text" else None,
            },
        )
    if payload.footer_text:
        components.append({"type": "FOOTER", "text": payload.footer_text})
    if payload.buttons:
        buttons_payload = []
        for b in payload.buttons:
            entry: dict[str, Any] = {"type": b.type.upper(), "text": b.text}
            if b.type == "url" and b.url:
                entry["url"] = b.url
            elif b.type == "phone_number" and b.phone_number:
                entry["phone_number"] = b.phone_number
            buttons_payload.append(entry)
        components.append({"type": "BUTTONS", "buttons": buttons_payload})

    existing = (
        await session.execute(
            _select(WhatsAppTemplate).where(
                WhatsAppTemplate.message_template_id == template.id
            )
        )
    ).scalar_one_or_none()

    # Meta's WA category (marketing / utility / authentication) lives on
    # the payload; default to ``marketing`` when the operator hasn't
    # picked one so the extension row satisfies its NOT NULL constraint.
    wa_category = payload.category or "marketing"

    if existing is None:
        row = WhatsAppTemplate(
            org_id=template.org_id,
            integration_id=integration.id,
            name=template.name,
            language=template.language,
            category=wa_category,
            status="DRAFT",
            body=template.body_text,
            header_type=payload.header_type,
            header_text=payload.header_text,
            footer_text=payload.footer_text,
            body_components=components,
            submission_status=WhatsAppTemplateSubmissionStatus.draft,
            message_template_id=template.id,
        )
        session.add(row)
    else:
        # Propagate the central row's identity fields onto the
        # extension too — otherwise Meta submission uses stale values
        # (e.g. sent to Meta with "Diwali Sale" when the operator
        # renamed the central row to "diwali_sale" to pass Meta's
        # snake_case rule). Same for language + body.
        existing.name = template.name
        existing.language = template.language
        existing.category = wa_category
        existing.header_type = payload.header_type
        existing.header_text = payload.header_text
        existing.footer_text = payload.footer_text
        existing.body = template.body_text
        existing.body_components = components
    await session.flush()


async def _load_wa_extension(
    session: AsyncSession, *, template: MessageTemplate
) -> None:
    """Attach a ``whatsapp`` attribute to the template row containing
    the extension's header / footer / buttons. Null on non-WA rows or
    when no extension exists. The router's ``TemplateRead.model_validate``
    picks it up via ORM mode without an explicit column.
    """
    from sqlalchemy import select as _select

    from src.app.core.integrations.whatsapp.models import WhatsAppTemplate
    from src.app.core.templates.schemas import (
        WhatsAppExtensionRead,
        WhatsAppTemplateButton,
    )

    if template.channel != ConversationChannel.whatsapp:
        setattr(template, "whatsapp", None)
        return

    row = (
        await session.execute(
            _select(WhatsAppTemplate).where(
                WhatsAppTemplate.message_template_id == template.id
            )
        )
    ).scalar_one_or_none()

    if row is None:
        setattr(template, "whatsapp", None)
        return

    # Reverse the components payload into structured buttons so the
    # frontend can render them without re-parsing Meta's shape.
    buttons: list[WhatsAppTemplateButton] | None = None
    if row.body_components:
        for c in row.body_components:
            if c.get("type") == "BUTTONS":
                buttons = []
                for b in c.get("buttons", []):
                    btype = str(b.get("type", "")).lower()
                    if btype not in {"url", "phone_number", "quick_reply"}:
                        continue
                    buttons.append(
                        WhatsAppTemplateButton(
                            type=btype,
                            text=b.get("text", ""),
                            url=b.get("url"),
                            phone_number=b.get("phone_number"),
                        )
                    )
                break

    setattr(
        template,
        "whatsapp",
        WhatsAppExtensionRead(
            category=row.category,
            header_type=row.header_type,
            header_text=row.header_text,
            footer_text=row.footer_text,
            buttons=buttons,
        ),
    )


async def create_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: TemplateCreate,
) -> MessageTemplate:
    """Insert template + initial version row in one transaction.

    The body is parsed for ``{{var}}`` references and the result is
    persisted on ``variables``. Raises
    :class:`DuplicateTemplateName` when the functional unique index
    on ``(org_id, lower(name), channel)`` rejects the insert (router
    surfaces as 409).
    """
    # Campaigns v1 Step 04 — sanitise HTML and resolve the body_text
    # that will land on the row. body_html only accepted for Email
    # (schema validator already rejected it for other channels).
    body_html = sanitize_email_html(payload.body_html) if payload.body_html else None
    body_text = _resolve_body_text(
        provided_text=payload.body_text,
        body_html=body_html,
        fallback_auto=payload.body_text_fallback_auto,
    )

    reject_jinja_statements(body_text)
    variables = extract_variable_paths(body_text)
    if body_html:
        # HTML placeholders are strings to the parser too; extending the
        # variable list keeps the manifest complete for anything that
        # only appears in the HTML branch (rare in practice).
        for path in extract_variable_paths(body_html):
            if path not in variables:
                variables.append(path)

    template = data_access.add_template(
        session,
        MessageTemplate(
            org_id=org_id,
            channel=payload.channel,
            name=payload.name,
            category=payload.category,
            language=payload.language,
            body_text=body_text,
            body_html=body_html,
            body_text_fallback_auto=payload.body_text_fallback_auto,
            subject=payload.subject,
            preview_text=payload.preview_text,
            variables=variables,
            internal_status=TemplateInternalStatus.draft,
            external_status=TemplateExternalStatus.n_a,
            current_version=1,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        ),
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateTemplateName(name=payload.name, channel=payload.channel.value) from exc

    data_access.add_template_version(
        session,
        MessageTemplateVersion(
            org_id=org_id,
            template_id=template.id,
            version=1,
            body_text=body_text,
            body_html=body_html,
            subject=payload.subject,
            variables=variables,
            changed_by_user_id=user_id,
            change_note="Initial version",
        ),
    )
    # Meta-specific extras — upsert the WA extension row so the
    # ``Submit to Meta`` flow has the header / footer / buttons ready
    # to send verbatim. Only touched on WA channel + when the payload
    # actually carries values.
    if (
        payload.channel == ConversationChannel.whatsapp
        and payload.whatsapp is not None
    ):
        await _upsert_wa_extension(session, template=template, payload=payload.whatsapp)
    await session.commit()
    await session.refresh(template)
    await _load_wa_extension(session, template=template)
    logger.info(
        "templates.create org=%s id=%s channel=%s name=%s",
        org_id,
        template.id,
        template.channel.value,
        template.name,
    )
    return template


async def update_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: TemplateUpdate,
    caller_can_publish: bool = False,
) -> MessageTemplate:
    """Edit the draft template. Bumps ``current_version`` and writes
    a new version row. Raises :class:`TemplateLocked` when the
    template's ``internal_status`` is not ``draft`` — except when the
    caller holds ``templates.publish`` (Owner / Admin), in which case
    edits are allowed through in_review / approved / published so the
    solo-operator flow doesn't force a duplicate-to-fork dance.
    Meta-immutable states (external_status = approved or pending) stay
    locked regardless, because editing there breaks the Meta contract.

    Subject / preview_text coherence with channel is checked here
    (the Pydantic validator on ``TemplateCreate`` doesn't see the
    persisted channel on a partial PATCH).
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)

    meta_immutable = template.external_status in (
        TemplateExternalStatus.approved,
        TemplateExternalStatus.pending,
    )
    if meta_immutable:
        raise TemplateLocked(template.internal_status.value)

    if template.internal_status in _EDIT_LOCKED_STATUSES and not caller_can_publish:
        raise TemplateLocked(template.internal_status.value)

    # Coherence: subject + preview_text + body_html only valid for email.
    if template.channel != ConversationChannel.email:
        if payload.subject is not None:
            raise ValueError(
                f"subject is only valid for email templates; "
                f"this template's channel is {template.channel.value}"
            )
        if payload.preview_text is not None:
            raise ValueError(
                f"preview_text is only valid for email templates; "
                f"this template's channel is {template.channel.value}"
            )
        if payload.body_html is not None:
            raise ValueError(
                f"body_html is only valid for email templates; "
                f"this template's channel is {template.channel.value}"
            )

    changed = False
    if payload.name is not None and payload.name != template.name:
        template.name = payload.name
        changed = True
    if payload.category is not None and payload.category != template.category:
        template.category = payload.category
        changed = True
    if payload.language is not None and payload.language != template.language:
        template.language = payload.language
        changed = True

    # Campaigns v1 Step 04 — body_html edit, sanitised before persist.
    if payload.body_html is not None:
        new_html = sanitize_email_html(payload.body_html)
        if new_html != template.body_html:
            template.body_html = new_html
            changed = True
    if (
        payload.body_text_fallback_auto is not None
        and payload.body_text_fallback_auto != template.body_text_fallback_auto
    ):
        template.body_text_fallback_auto = payload.body_text_fallback_auto
        changed = True

    if payload.body_text is not None and payload.body_text != template.body_text:
        reject_jinja_statements(payload.body_text)
        template.body_text = payload.body_text
        changed = True
    elif (
        payload.body_text is None
        and payload.body_html is not None
        and template.body_html is not None
        and (template.body_text_fallback_auto if payload.body_text_fallback_auto is None
             else payload.body_text_fallback_auto)
    ):
        # HTML was edited without an explicit text override — auto-derive
        # the plain-text fallback so dispatch's multipart branch has a
        # coherent pair.
        derived = derive_plain_text(template.body_html or "")
        if derived and derived != template.body_text:
            reject_jinja_statements(derived)
            template.body_text = derived
            changed = True

    if payload.subject is not None and payload.subject != template.subject:
        template.subject = payload.subject
        changed = True
    if payload.preview_text is not None and payload.preview_text != template.preview_text:
        template.preview_text = payload.preview_text
        changed = True

    # Rebuild the variable manifest across both bodies if anything body-
    # related changed. Cheap; keeps the manifest coherent with either
    # side of the edit.
    if changed:
        merged: list[str] = list(extract_variable_paths(template.body_text or ""))
        if template.body_html:
            for path in extract_variable_paths(template.body_html):
                if path not in merged:
                    merged.append(path)
        template.variables = merged

    # Meta-specific extras — patch the WA extension row. Independent of
    # ``changed`` above because the operator may only be editing WA
    # fields (footer / buttons) without touching the body.
    wa_touched = False
    if (
        template.channel == ConversationChannel.whatsapp
        and payload.whatsapp is not None
    ):
        await _upsert_wa_extension(session, template=template, payload=payload.whatsapp)
        wa_touched = True

    if not changed and not wa_touched:
        await _load_wa_extension(session, template=template)
        return template

    new_version = template.current_version + 1
    template.current_version = new_version
    template.updated_by_user_id = user_id
    template.updated_at = func.now()

    data_access.add_template_version(
        session,
        MessageTemplateVersion(
            org_id=org_id,
            template_id=template.id,
            version=new_version,
            body_text=template.body_text,
            body_html=template.body_html,
            subject=template.subject,
            variables=template.variables,
            changed_by_user_id=user_id,
            change_note=payload.change_note,
        ),
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Duplicate ``(template_id, version)`` is the only IntegrityError
        # that can fire here (the unique index from migration 0117), and
        # only if two concurrent updates race. Surface as a generic
        # conflict so the router 409s; the caller retries with a fresh
        # read.
        raise DuplicateTemplateName(name=template.name, channel=template.channel.value) from exc

    await session.refresh(template)
    await _load_wa_extension(session, template=template)
    logger.info(
        "templates.update org=%s id=%s new_version=%d",
        org_id,
        template.id,
        new_version,
    )
    return template


async def archive_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> MessageTemplate:
    """Set ``internal_status='archived'``. Idempotent — archiving an
    already-archived template is a no-op (no second audit row, no
    timestamp bump). Does not touch ``external_status`` — a Meta-
    approved template stays approved on Meta's side even if our org
    archives the local copy.
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status == TemplateInternalStatus.archived:
        return template

    template.internal_status = TemplateInternalStatus.archived
    template.updated_by_user_id = user_id
    template.updated_at = func.now()
    await session.commit()
    await session.refresh(template)
    logger.info(
        "templates.archive org=%s id=%s",
        org_id,
        template.id,
    )
    return template


async def set_active(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    active: bool,
    user_id: uuid.UUID | None,
) -> MessageTemplate:
    """Flip ``is_active`` on / off. Idempotent — the current row's flag
    already matching ``active`` short-circuits without an audit row or
    ``updated_at`` bump.

    Distinct from ``archive`` — an inactive template stays in whatever
    internal_status it was (published rows stay ``published``, drafts
    stay drafts). It just gets filtered out of every send path.
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if bool(template.is_active) == bool(active):
        return template
    template.is_active = bool(active)
    template.updated_by_user_id = user_id
    template.updated_at = func.now()
    await session.commit()
    await session.refresh(template)
    logger.info(
        "templates.set_active org=%s id=%s active=%s",
        org_id,
        template.id,
        active,
    )
    return template


__all__: list[str] = [
    "archive_template",
    "create_template",
    "get_template",
    "get_version",
    "list_templates",
    "list_versions",
    "set_active",
    "update_template",
]
