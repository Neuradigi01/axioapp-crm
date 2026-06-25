"""Data-access layer for the contacts module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Two duplicate-by-shape patterns in the codebase: by id (the canonical
"hydrate this contact" call) and by phone (walk-in reception's
"do we already know this number?" check + conversation routing's
inbound-message-to-contact resolver).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.models import Contact


async def get_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> Contact | None:
    """Resolve a contact by its UUID PK.

    Tenant scoping is applied automatically by the `do_orm_execute`
    listener (Contact is `TenantScoped`), so the row is only returned
    when it belongs to the active request's org. Callers that run
    outside a tenant context (Celery, scripts) must set
    `RequestContext.org_id` first.
    """
    result = await session.execute(
        select(Contact).where(Contact.id == contact_id)
    )
    return result.scalar_one_or_none()


async def get_contact_by_phone(
    session: AsyncSession, phone: str
) -> Contact | None:
    """Resolve a contact by phone number.

    Used by walk-in reception (existing-customer detection) and by
    the conversation router (inbound WhatsApp / SMS → contact mapping).
    The phone column is indexed but not unique — multiple contacts
    can share a number across orgs (different tenants). The tenant
    auto-filter narrows the result to the active org.
    """
    result = await session.execute(
        select(Contact).where(Contact.phone == phone)
    )
    return result.scalar_one_or_none()


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Register an already-constructed Contact for INSERT. Caller
    commits or flushes. Used by webhook intake paths that need to
    materialise a placeholder contact for an unknown phone number
    (conversations, walk-ins)."""
    session.add(contact)


__all__ = ["get_contact", "get_contact_by_phone", "insert_contact"]
