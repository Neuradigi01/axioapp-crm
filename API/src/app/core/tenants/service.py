"""Tenant (organization) service.

Helpers around the `organizations` table. Used by signup, by every
endpoint that needs to hydrate the tenant row off a JWT's `org_id`
claim, and by ownership transfer.
"""

from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants import data_access as tenants_data_access
from src.app.core.tenants.models import Organization

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    base = _SLUG_CLEAN.sub("-", name.lower()).strip("-")
    return base[:48] or "workspace"


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
        if not await tenants_data_access.slug_taken(session, slug):
            break
        slug = f"{base_slug}-{secrets.token_hex(2)}"
    else:
        slug = f"{base_slug}-{secrets.token_hex(4)}"

    org = tenants_data_access.add_organization(
        session,
        Organization(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            template_id=template_id,
            created_via=created_via,
        ),
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise

    # tasks/automation-engine Step 5 — install default automation
    # seeds inside the same transaction. A signup that later rolls
    # back also rolls back the seeded template + trigger. Idempotent
    # — re-runs (from the backfill migration's pre-existing-org
    # sweep) never duplicate.
    from src.app.core.automation.seeds import install_default_org_seeds

    await install_default_org_seeds(session, org_id=org.id)

    return org


async def get_organization_by_id(session: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    """Resolve an organisation by its UUID PK.

    Thin service wrapper over the tenants DAL so callers in other
    modules don't reach into `tenants.data_access` directly. Returns
    `None` on miss; callers decide how to surface that.
    """
    return await tenants_data_access.get_organization_by_id(session, org_id)


async def get_organization_by_slug(session: AsyncSession, slug: str) -> Organization | None:
    """Resolve an organisation by URL slug.

    Public service wrapper so router code never reaches into the
    tenants DAL directly. Returns `None` for unknown slugs — the
    caller (auth login / staff portal) surfaces an "invalid
    credentials" response to avoid leaking which slugs exist.
    """
    return await tenants_data_access.get_organization_by_slug(session, slug)
