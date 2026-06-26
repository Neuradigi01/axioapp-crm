"""Data-access layer for the central template library.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``.

Three concerns, kept in one file per the project's layered-architecture
spec (manager-locked 2026-06-25):

  * ``tbl_message_templates``     — lookups + filterable list
  * ``tbl_message_template_versions`` — version-history lookups
  * ``tbl_sms_dlt_templates``     — SMS-DLT extension lookups
    (companion writes live in :mod:`core.templates.sms_extension`)

Tenant scoping is applied automatically by the ``do_orm_execute``
listener on every SELECT, but we also pass ``org_id`` explicitly in
the WHERE clause as a belt to the suspenders — defends callers that
forget to set ``RequestContext.org_id`` (Celery tasks, scripts).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.sms_extension import SMSDLTTemplate


# --- tbl_message_templates ----------------------------------------------


async def get_by_external_provider_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    external_provider_id: str,
) -> MessageTemplate | None:
    """Reverse lookup — given the provider's template id (Meta /
    SMS-DLT), return the central row in this org. Used by the Step-14
    status-sync path + the Meta webhook handler to update the central
    row's ``external_status`` when Meta fires a status_update event."""
    result = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.org_id == org_id,
            MessageTemplate.external_provider_id == external_provider_id,
        )
    )
    return result.scalar_one_or_none()


async def get_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> MessageTemplate | None:
    """Resolve a template by its UUID PK. ``None`` if missing or
    cross-tenant (callers translate to :class:`TemplateNotFound`)."""
    result = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


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
    """Filterable + paginated list. ``q`` matches against ``name`` or
    ``body_text`` (case-insensitive). Returns ``(rows, total)``."""
    base = select(MessageTemplate).where(MessageTemplate.org_id == org_id)

    if channel is not None:
        base = base.where(MessageTemplate.channel == channel)
    if internal_status is not None:
        base = base.where(MessageTemplate.internal_status == internal_status)
    if external_status is not None:
        base = base.where(MessageTemplate.external_status == external_status)
    if q:
        pattern = f"%{q.lower()}%"
        base = base.where(
            or_(
                func.lower(MessageTemplate.name).like(pattern),
                func.lower(MessageTemplate.body_text).like(pattern),
            )
        )

    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(MessageTemplate.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


# --- tbl_message_template_versions --------------------------------------


async def list_versions(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[MessageTemplateVersion]:
    """All versions of ``template_id``, newest first."""
    rows = (
        (
            await session.execute(
                select(MessageTemplateVersion)
                .where(MessageTemplateVersion.template_id == template_id)
                .order_by(MessageTemplateVersion.version.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_version(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    version: int,
) -> MessageTemplateVersion | None:
    """One specific past version. ``None`` if absent — the service
    raises :class:`TemplateNotFound` (no separate exception so clients
    can't distinguish "template missing" from "version missing")."""
    result = await session.execute(
        select(MessageTemplateVersion).where(
            MessageTemplateVersion.template_id == template_id,
            MessageTemplateVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


# --- tbl_sms_dlt_templates ----------------------------------------------


async def get_dlt_metadata(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> SMSDLTTemplate | None:
    """Resolve the DLT extension row keyed on the central template
    id. ``None`` when the SMS template has never had DLT metadata
    captured (fresh draft)."""
    result = await session.execute(
        select(SMSDLTTemplate).where(
            SMSDLTTemplate.message_template_id == template_id,
            SMSDLTTemplate.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def find_by_dlt_template_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    dlt_template_id: str,
) -> SMSDLTTemplate | None:
    """Reverse lookup by the TRAI-issued template id. Used by future
    DLT status-sync paths to route an external status update to the
    matching central row."""
    result = await session.execute(
        select(SMSDLTTemplate).where(
            SMSDLTTemplate.org_id == org_id,
            SMSDLTTemplate.dlt_template_id == dlt_template_id,
        )
    )
    return result.scalar_one_or_none()


def add_template(
    session: AsyncSession, template: MessageTemplate
) -> MessageTemplate:
    """Stage a new `tbl_message_templates` row in the unit-of-work."""
    session.add(template)
    return template


def add_template_version(
    session: AsyncSession, version: MessageTemplateVersion
) -> MessageTemplateVersion:
    """Stage a new `tbl_message_template_versions` row in the unit-of-work."""
    session.add(version)
    return version


__all__ = [
    "add_template",
    "add_template_version",
    "find_by_dlt_template_id",
    "get_by_external_provider_id",
    "get_dlt_metadata",
    "get_template",
    "get_version",
    "list_templates",
    "list_versions",
]
