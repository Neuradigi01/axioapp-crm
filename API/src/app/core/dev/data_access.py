"""Data-access layer for the dev module.

Pure query helpers — no transactions, no business logic. Leaf module;
never imports `service.py` or `router.py`.

The only consumer today is `/api/v1/_dev/demo-logins`, which lists every
seeded demo login for the login-page "Test logins" dropdown.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.dev.models import DemoCredential
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User, UserInfo


async def list_demo_login_rows(session: AsyncSession) -> list[Row]:
    """Return every demo login the seed scripts created.

    Joins tbl_user_login (legacy users), tbl_user_info (email +
    first_name), tbl_organization_members (is_demo flag), tbl_organizations
    (slug + name + template_id), and tbl_demo_credentials (plaintext
    password kept for the dev-only dropdown). Rows are ordered so Core
    CRM entries come first, then Furniture, then anything else —
    matches what most reviewers expect to click through.
    """
    stmt = (
        select(
            UserInfo.email.label("identifier"),
            DemoCredential.plain_password.label("password"),
            DemoCredential.label.label("label_db"),
            Organization.slug.label("org_slug"),
            Organization.name.label("org_name"),
            Organization.template_id.label("template_id"),
        )
        .select_from(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .join(
            Organization,
            Organization.id == OrganizationMember.organization_id,
        )
        # DemoCredential.user_id is a UUID FK kept against the original
        # users.id values; tbl_user_login.legacy_uuid preserves them
        # 1:1 from the 0032 migration.
        .join(DemoCredential, DemoCredential.user_id == User.legacy_uuid)
        .where(OrganizationMember.is_demo.is_(True))
        .where(OrganizationMember.is_active.is_(True))
        .order_by(Organization.template_id.asc(), UserInfo.first_name.asc())
    )
    return list((await session.execute(stmt)).all())
