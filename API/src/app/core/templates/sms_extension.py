"""SMS-DLT extension model + service for the central template library.

The :class:`SMSDLTTemplate` ORM row carries the TRAI-mandated DLT
metadata (Distributed Ledger Technology — India's SMS sender
registry). Created on first DLT capture against a central template
row; deleted via CASCADE when the central row is archived /
deleted.

Pure CRUD service — reads delegate to :mod:`core.templates.data_access.sms_dlt`;
writes happen here so the audit log + updated_at flow cleanly. DLT
portal submission is NOT in scope (TRAI portals are externally
mandated; standard CRM pattern is manual ID capture).
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.templates.exceptions import TemplateNotFound
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


logger = logging.getLogger(__name__)


class SMSDLTContentCategory(str, enum.Enum):
    """TRAI's four content classifications. Distinct from our
    internal ``TemplateCategory`` (marketing / transactional /
    service) — that's how the CRM classifies templates for DPDP /
    frequency-cap purposes; this is how TRAI classifies them for
    sender-id routing + cost."""

    transactional = "transactional"
    promotional = "promotional"
    service_explicit = "service_explicit"
    service_implicit = "service_implicit"


class SMSDLTTemplateStatus(str, enum.Enum):
    """The DLT portal's verdict on the registration.

    Operator updates this manually after they finish the portal
    submission (the portals don't have webhooks; manual sync is the
    standard pattern)."""

    registered = "registered"
    pending = "pending"
    rejected = "rejected"


sms_dlt_content_category_enum = ENUM(
    SMSDLTContentCategory,
    name="sms_dlt_content_category",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)

sms_dlt_template_status_enum = ENUM(
    SMSDLTTemplateStatus,
    name="sms_dlt_template_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class SMSDLTTemplate(Base, TenantScoped):
    """Per-template DLT registration metadata. One row per central
    SMS template at most."""

    __tablename__ = "tbl_sms_dlt_templates"
    __table_args__ = (
        UniqueConstraint(
            "message_template_id",
            name="uq_sms_dlt_message_template_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    message_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    dlt_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dlt_template_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dlt_content_category: Mapped[SMSDLTContentCategory] = mapped_column(
        sms_dlt_content_category_enum,
        nullable=False,
        server_default=sql_text("'transactional'"),
    )
    dlt_header: Mapped[Optional[str]] = mapped_column(
        String(6), nullable=True
    )
    dlt_principal_entity_id: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    dlt_template_status: Mapped[SMSDLTTemplateStatus] = mapped_column(
        sms_dlt_template_status_enum,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    dlt_registered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dlt_rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )


# --- service helpers ---------------------------------------------------


async def get_dlt_metadata(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> SMSDLTTemplate | None:
    """Read-through to the DAL — service-side helper so callers don't
    need to import the DAL directly."""
    from src.app.core.templates.data_access import sms_dlt as sms_dlt_da

    return await sms_dlt_da.get_dlt_metadata(
        session, org_id=org_id, template_id=template_id
    )


async def set_dlt_metadata(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: dict,
) -> SMSDLTTemplate:
    """Upsert the DLT metadata row for ``template_id``.

    ``payload`` is a dict of the fields the operator just edited; any
    omitted key keeps its current value. The central template row
    must exist + be SMS-channel — caller's responsibility to enforce
    (the router does this via :func:`templates_service.get_template`).
    """
    from src.app.core.templates import service as templates_service

    template = await templates_service.get_template(
        session, org_id=org_id, template_id=template_id
    )
    if template is None:
        raise TemplateNotFound(str(template_id))

    row = await get_dlt_metadata(
        session, org_id=org_id, template_id=template_id
    )
    if row is None:
        row = SMSDLTTemplate(
            org_id=org_id, message_template_id=template_id
        )
        session.add(row)
        await session.flush()

    # Apply explicitly-supplied fields only — preserves untouched ones.
    for field in (
        "dlt_entity_id",
        "dlt_template_id",
        "dlt_content_category",
        "dlt_header",
        "dlt_principal_entity_id",
        "dlt_template_status",
        "dlt_registered_at",
        "dlt_rejection_reason",
    ):
        if field in payload:
            value = payload[field]
            if field == "dlt_header" and isinstance(value, str):
                # TRAI mandates the header is a 6-char uppercase
                # alphanumeric — normalise on the way in.
                value = value.strip().upper()[:6] or None
            setattr(row, field, value)

    await session.commit()
    await session.refresh(row)
    logger.info(
        "templates.sms_dlt.set org=%s template=%s status=%s",
        org_id,
        template_id,
        row.dlt_template_status.value,
    )
    return row


__all__ = [
    "SMSDLTContentCategory",
    "SMSDLTTemplate",
    "SMSDLTTemplateStatus",
    "get_dlt_metadata",
    "set_dlt_metadata",
]
