"""Data-access layer for the lead-imports sub-package."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.leads.imports.models import LeadImport, LeadImportStatus


def add_import(session: AsyncSession, row: LeadImport) -> LeadImport:
    """Stage a new lead-import row in the unit-of-work."""
    session.add(row)
    return row


async def get_import_by_id(
    session: AsyncSession, import_id: uuid.UUID
) -> LeadImport | None:
    """Single import row lookup — tenant filter handles cross-org cull."""
    result = await session.execute(
        select(LeadImport).where(LeadImport.id == import_id)
    )
    return result.scalar_one_or_none()


async def count_imports_filtered(
    session: AsyncSession,
    *,
    status_filter: Optional[LeadImportStatus],
    source_platform: Optional[str],
) -> int:
    """Total imports matching the lifecycle / platform filters."""
    stmt = select(func.count()).select_from(LeadImport)
    if status_filter is not None:
        stmt = stmt.where(LeadImport.status == status_filter)
    if source_platform:
        stmt = stmt.where(LeadImport.source_platform == source_platform)
    return int((await session.execute(stmt)).scalar_one())


async def list_imports_page(
    session: AsyncSession,
    *,
    status_filter: Optional[LeadImportStatus],
    source_platform: Optional[str],
    offset: int,
    limit: int,
) -> list[LeadImport]:
    """Page of imports sorted newest-first."""
    stmt = select(LeadImport)
    if status_filter is not None:
        stmt = stmt.where(LeadImport.status == status_filter)
    if source_platform:
        stmt = stmt.where(LeadImport.source_platform == source_platform)
    stmt = (
        stmt
        .order_by(LeadImport.created_at.desc(), LeadImport.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def list_custom_field_keys(
    session: AsyncSession,
) -> list[str]:
    """Every contact-or-lead custom-field key in the active org.

    Used by the mapping validator to whitelist `custom_data.<key>`
    targets.
    """
    rows = (
        await session.execute(
            select(CustomFieldDefinition.field_key).where(
                CustomFieldDefinition.entity_type.in_(("contact", "lead"))
            )
        )
    ).all()
    return [r.field_key for r in rows]


__all__ = [
    "add_import",
    "count_imports_filtered",
    "get_import_by_id",
    "list_custom_field_keys",
    "list_imports_page",
]
