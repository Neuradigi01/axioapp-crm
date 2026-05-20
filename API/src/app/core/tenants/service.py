"""Tenant (organization) service.

Helpers around the `organizations` table. Today only `create_organization`
lives here — used by the signup flow when a brand-new visitor lands.
"""
from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
    pack_id: str = "core",
) -> Organization:
    """Insert a new organization row.

    `slug` is derived from `name`; on collision a short random suffix is
    appended until unique. Caller owns the transaction (no commit here).
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
        pack_id=pack_id,
        created_via=created_via,
    )
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise
    return org
