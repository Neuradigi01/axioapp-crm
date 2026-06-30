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
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MessageTemplate], int]:
    """Filterable + paginated list. Returns ``(rows, total)``."""
    return await data_access.list_templates(
        session,
        org_id=org_id,
        channel=channel,
        internal_status=internal_status,
        external_status=external_status,
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
    reject_jinja_statements(payload.body_text)
    variables = extract_variable_paths(payload.body_text)

    template = data_access.add_template(
        session,
        MessageTemplate(
            org_id=org_id,
            channel=payload.channel,
            name=payload.name,
            category=payload.category,
            language=payload.language,
            body_text=payload.body_text,
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
            body_text=payload.body_text,
            subject=payload.subject,
            variables=variables,
            changed_by_user_id=user_id,
            change_note="Initial version",
        ),
    )
    await session.commit()
    await session.refresh(template)
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
) -> MessageTemplate:
    """Edit the draft template. Bumps ``current_version`` and writes
    a new version row. Raises :class:`TemplateLocked` when the
    template's ``internal_status`` is not ``draft``.

    Subject / preview_text coherence with channel is checked here
    (the Pydantic validator on ``TemplateCreate`` doesn't see the
    persisted channel on a partial PATCH).
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)

    if template.internal_status in _EDIT_LOCKED_STATUSES:
        raise TemplateLocked(template.internal_status.value)

    # Coherence: subject + preview_text only valid for email.
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
    if payload.body_text is not None and payload.body_text != template.body_text:
        reject_jinja_statements(payload.body_text)
        template.body_text = payload.body_text
        template.variables = extract_variable_paths(payload.body_text)
        changed = True
    if payload.subject is not None and payload.subject != template.subject:
        template.subject = payload.subject
        changed = True
    if payload.preview_text is not None and payload.preview_text != template.preview_text:
        template.preview_text = payload.preview_text
        changed = True

    if not changed:
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


__all__: list[str] = [
    "archive_template",
    "create_template",
    "get_template",
    "get_version",
    "list_templates",
    "list_versions",
    "update_template",
]
