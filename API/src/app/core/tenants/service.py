"""Tenant (organization) service.

Helpers around the `organizations` table. Used by signup, by every
endpoint that needs to hydrate the tenant row off a JWT's `org_id`
claim, and by ownership transfer.
"""
from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants import data_access as tenants_data_access
from src.app.core.tenants.models import Organization


_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    base = _SLUG_CLEAN.sub("-", name.lower()).strip("-")
    return base[:48] or "workspace"


async def _slug_taken(session: AsyncSession, slug: str) -> bool:
    result = await session.execute(
        select(Organization.id).where(Organization.slug == slug)
    )
    return result.scalar_one_or_none() is not None


async def create_organization(
    session: AsyncSession,
    *,
    name: str,
    created_via: str = "normal_signup",
    template_id: str = "pending",
) -> Organization:
    """Insert a new organization row.

    `slug` is derived from `name`; on collision a short random suffix is
    appended until unique. Caller owns the transaction (no commit here).
    `template_id` defaults to the `"pending"` sentinel — callers that
    finalize the org synchronously (e.g. the legacy
    `register_with_new_org` path or seed scripts) override it with a
    real template like `"base"` or `"furniture"`.
    """
    base_slug = _slugify(name)
    slug = base_slug
    for _ in range(8):
        if not await _slug_taken(session, slug):
            break
        slug = f"{base_slug}-{secrets.token_hex(2)}"
    else:
        slug = f"{base_slug}-{secrets.token_hex(4)}"

    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        template_id=template_id,
        created_via=created_via,
    )
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise
    return org


async def get_organization_by_id(
    session: AsyncSession, org_id: uuid.UUID
) -> Organization | None:
    """Resolve an organisation by its UUID PK.

    Thin service wrapper over the tenants DAL so callers in other
    modules don't reach into `tenants.data_access` directly. Returns
    `None` on miss; callers decide how to surface that.
    """
    return await tenants_data_access.get_organization_by_id(session, org_id)
