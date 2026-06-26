"""Data-access layer for the tenants module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Two helpers cover every duplicate-by-shape callsite found in the
audit: id-based (the canonical post-auth tenant fetch) and slug-based
(the login flow). Both return `None` on miss; callers decide whether
that's a 404, an invalid-credentials response, or a silent fallback.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants.models import Organization


async def get_organization_by_id(
    session: AsyncSession, org_id: uuid.UUID
) -> Organization | None:
    """Resolve an organisation by its UUID PK.

    Used by every endpoint that needs to hydrate the tenant row off
    the JWT's `org_id` claim — dashboard, invitations, contacts list,
    leads list, conversations email adapter, etc.
    """
    result = await session.execute(
        select(Organization).where(Organization.id == org_id)
    )
    return result.scalar_one_or_none()


async def get_organization_by_slug(
    session: AsyncSession, slug: str
) -> Organization | None:
    """Resolve an organisation by its URL slug.

    Used by the login flow (`POST /auth/login?org_slug=...`) and the
    staff-portal entry (`POST /staff/login`). Returns None when the
    slug is unknown — the caller surfaces a generic
    "invalid credentials" response to avoid leaking which orgs exist.
    """
    result = await session.execute(
        select(Organization).where(Organization.slug == slug)
    )
    return result.scalar_one_or_none()


async def slug_taken(session: AsyncSession, slug: str) -> bool:
    """True iff an organisation already uses this slug."""
    result = await session.execute(
        select(Organization.id).where(Organization.slug == slug)
    )
    return result.scalar_one_or_none() is not None


def add_organization(
    session: AsyncSession, organization: Organization
) -> Organization:
    """Stage a new `tbl_organizations` row in the unit-of-work."""
    session.add(organization)
    return organization


__all__ = [
    "add_organization",
    "get_organization_by_id",
    "get_organization_by_slug",
    "slug_taken",
]
