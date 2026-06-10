"""Outbound billing email dispatch — Step 20.

Replaces the Step 6 stub. The function still has the same
`send_billing_email(...)` signature, so every existing emit-site
(`lifecycle.py`, the webhook handlers) picks up real delivery without
a code change.

Lifecycle:
  1. Resolve the org's Owner — the first active member whose role is
     marked "is_system" or named "owner". Falls back to *any* active
     member if no Owner-equivalent exists so the email isn't silently
     dropped.
  2. Render the template via `email_templates.render`.
  3. Hand `Email(...)` to whichever `EmailBackend` is configured (log
     backend in dev, SMTP backend when `EMAIL_ENABLED=true`).

Contract — never raises. Every call site is downstream of a
user-visible action; a misconfigured SMTP credential must not turn a
successful checkout into a 500.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.email_templates import render as render_template
from src.app.core.users.models import OrganizationMember, UserInfo
from src.app.shared.email import Email, get_email_backend
# `async_session` is looked up at call time via this module reference so
# the conftest patch (`src.core.db.async_session = TestSession`) takes
# effect during tests. Importing it as a name would freeze the binding
# to the prod session factory at import time.
from src.core import db as _core_db

log = logging.getLogger(__name__)


BillingEmailKey = Literal[
    "trial_ending_soon",
    "trial_expired",
    "subscription_archived",
    "payment_succeeded",
    "payment_failed",
    "seats_added",
    "plan_changed",
]


async def send_billing_email(
    *,
    org_id: uuid.UUID,
    template_key: BillingEmailKey,
    context: dict[str, Any] | None = None,
) -> None:
    """Queue a billing email for the org's Owner.

    Best-effort by contract — never raises. Failures are logged and
    swallowed so the caller's parent flow (webhook handler, lifecycle
    task) continues uninterrupted.
    """
    ctx = dict(context or {})
    try:
        async with _core_db.async_session() as session:
            recipient = await _resolve_owner_email(session, org_id)
            if recipient is None:
                log.warning(
                    "billing_email.no_owner org_id=%s template=%s",
                    org_id, template_key,
                )
                return

            email_address, first_name, org_name = recipient
            ctx.setdefault("owner_first_name", first_name)
            ctx.setdefault("org_name", org_name)

            rendered = render_template(template_key, ctx)
            if rendered is None:
                log.warning(
                    "billing_email.unknown_template template=%s",
                    template_key,
                )
                return

            subject, body_html, body_text = rendered
            email = Email(
                to=email_address,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )
            await get_email_backend().send(email)
            log.info(
                "billing_email.sent org_id=%s template=%s to=%s",
                org_id, template_key, email_address,
            )
    except Exception:  # noqa: BLE001
        # Per the documented contract — never let an email failure
        # propagate to a user-visible 5xx.
        log.exception(
            "billing_email.failed org_id=%s template=%s",
            org_id, template_key,
        )


async def _resolve_owner_email(
    session: AsyncSession, org_id: uuid.UUID,
) -> tuple[str, str | None, str | None] | None:
    """Find the org's Owner email + first_name + org_name.

    Preference order:
      1. Member whose role name is exactly "owner" (post-RBAC-Ownership
         convention).
      2. Member with `billing.manage` permission on their role
         (Owner-only per Step 19).
      3. Any active member (defensive fallback).

    Returns `(email, first_name, org_name)` or `None` if the org has
    no active members or the chosen member has no email on file.
    """
    from src.app.core.permissions.models import (
        Permission,
        Role,
        RolePermission,
    )
    from src.app.core.tenants.models import Organization

    # Preferred: role.name == "owner".
    stmt_owner = (
        select(UserInfo.email, UserInfo.first_name, Organization.name)
        .select_from(OrganizationMember)
        .join(Role, Role.id == OrganizationMember.role_id)
        .join(UserInfo, UserInfo.member_id == OrganizationMember.user_member_id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
            Role.name == "owner",
        )
        .limit(1)
    )
    row = (await session.execute(stmt_owner)).first()
    if row is not None and row[0]:
        return (row[0], row[1], row[2])

    # Fallback: member with `billing.manage` granted.
    stmt_manage = (
        select(UserInfo.email, UserInfo.first_name, Organization.name)
        .select_from(OrganizationMember)
        .join(Role, Role.id == OrganizationMember.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .join(UserInfo, UserInfo.member_id == OrganizationMember.user_member_id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
            Permission.key == "billing.manage",
        )
        .limit(1)
    )
    row = (await session.execute(stmt_manage)).first()
    if row is not None and row[0]:
        return (row[0], row[1], row[2])

    # Defensive fallback — any active member.
    stmt_any = (
        select(UserInfo.email, UserInfo.first_name, Organization.name)
        .select_from(OrganizationMember)
        .join(UserInfo, UserInfo.member_id == OrganizationMember.user_member_id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    row = (await session.execute(stmt_any)).first()
    if row is None or not row[0]:
        return None
    return (row[0], row[1], row[2])
