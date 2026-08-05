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

    # tasks/workflows-absorb-automation Step 2 — install the ten preset
    # single-step workflows (User Welcome / Lead Confirmation /
    # Appointment Reminders / Invoice notifications / Birthday / Lead
    # Stale). Replaces the pre-cutover call to
    # ``core.automation.seeds.install_default_org_seeds`` — new orgs no
    # longer install any automation triggers, only their workflow
    # equivalents. Same transaction so a rolled-back signup also rolls
    # back the seeded template + workflow rows. Idempotent — re-runs
    # from the backfill migration never duplicate.
    from src.app.core.workflows.seeds import install_preset_workflows

    await install_preset_workflows(session, org_id=org.id, user_id=None)

    # tasks/workflows Step 20 — install the 15 default core workflows
    # for the new org. Drafts by default — operator activates per
    # workflow. Idempotent: skips templates whose canonical name is
    # already present (re-running from the backfill is safe). Soft-
    # fails per-template inside the seeder so one bad clone doesn't
    # roll back the rest of org creation.
    from src.app.core.workflows.seeds import install_seeded_workflows

    try:
        await install_seeded_workflows(session, org_id=org.id, user_id=None)
    except Exception:
        # Hard catch — workflow seeding must NEVER block org creation.
        # The backfill migration picks up any missed installs.
        import logging

        logging.getLogger(__name__).exception(
            "tenants.create_organization workflow_seed_failed org=%s", org.id
        )

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
