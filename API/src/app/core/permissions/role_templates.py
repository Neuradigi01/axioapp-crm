"""Role-template registry + installer.

Vertical-neutral defaults that get stamped into a freshly-created org
(by the signup flow in `core.auth.service.register_with_new_org`).
Owner / Admin / Employee are all auto-instantiated on org creation
(option A decision, locked 2026-05-20). All three land as ordinary
rows in `roles` — the Owner row carries `is_system=true` so it's
locked, Admin and Employee are `is_system=false` and Owner-editable.

The permission lists below are **core-only** — they intentionally
exclude pack-specific keys (`inventory.*`, `custom_orders.*`,
`field_visits.*`, `pos.*`). Self-signup orgs start with
`template_id='pending'` (finalized to a real template at onboarding),
so granting pack permissions would surface pack modules in the
sidebar even before a pack is installed. Pack permissions get added
back if/when the pack is installed on the org (future Phase 4 work).

`permission_keys` lists are resolved against the live `permissions`
registry at install time. Unknown keys raise — better to break the
install than silently miss a grant.

The seeded demo orgs (`demo`, `core-demo`) use their own hand-rolled
inserts in `scripts/seed_*.py`. The template registry here is the
canonical source for *self-signup* orgs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.permissions.models import Permission, Role, RolePermission


class UnknownPermissionKey(RuntimeError):
    """A template references a key not present in the live registry."""


class OwnerAlreadyExists(RuntimeError):
    """Attempted to install a second Owner role into an org."""


_CORE_ADMIN_KEYS: list[str] = [
    "users.read",
    "users.write",
    "roles.read",
    "roles.write",
    "audit.read",
    "custom_fields.read",
    "custom_fields.write",
    "settings.read",
    "settings.write",
    "settings.standard_fields.manage",
    "settings.integrations.manage",
    "settings.integrations.embed.manage",
    "contacts.read",
    "contacts.write",
    "contacts.reassign",
    "leads.read",
    "leads.write",
    "leads.import",
    "leads.reassign",
    "leads.export",
    "appointments.read",
    "appointments.write",
    "appointments.reassign",
    "walkins.read",
    "walkins.write",
    "walkins.reassign",
    "walk_ins.read",
    "walk_ins.write",
    "catalog.read",
    "catalog.write",
    "conversations.read",
    "conversations.write",
    # whatsapp-platform-upgrade Step 14 — tag CRUD. Owner + Admin only.
    "settings.conversations.manage",
    "calls.read",
    "calls.write",
    "calls.outcomes.manage",
    "reviews.read",
    "reviews.write",
    "campaigns.read",
    "campaigns.write",
    "campaigns.send",
    # whatsapp-platform-upgrade Step 8 — Admin manages templates and
    # may submit to Meta. Junior roles get `whatsapp.templates.read`
    # via the picker but not write/submit by default.
    "whatsapp.templates.read",
    "whatsapp.templates.write",
    "whatsapp.templates.submit",
    # whatsapp-platform-upgrade Step 11 — business profile editor.
    "whatsapp.business_profile.manage",
    # whatsapp-platform-upgrade Step 17 — keyword automation rules.
    "whatsapp.automation.manage",
    # whatsapp-platform-upgrade Step 20 — conversation analytics
    # dashboard (volume / response time / outcomes / leaderboard).
    # Owner + Admin get visibility; Employee + junior roles do not by
    # default — manager-spec: "is WhatsApp working" is a leadership
    # question, not floor staff.
    "whatsapp.analytics.read",
    # whatsapp-platform-upgrade Step 22 — manual override of contact
    # opt-in status. Read of `/contacts/{id}/opt-in` is gated on
    # `contacts.read` (every staffer can see the state); only Owner
    # + Admin can force-flip via the manual API. DPDP audit log
    # records the override regardless.
    "whatsapp.opt_in.manage",
    # whatsapp-platform-upgrade Step 25 — WhatsApp Flows (in-chat
    # forms) library. Same Owner/Admin-only default as the rest of
    # the WhatsApp admin surfaces; junior roles don't see the page.
    "whatsapp.flows.manage",
    "tasks.read",
    "tasks.write",
    "pipelines.read",
    "pipelines.manage",
    "pipelines.write",
    "activities.read",
    "activities.write",
    "staff.read",
    "staff.write",
    "attendance.write",
    "billing.read",
    "billing.write",
    "saved_views.use",
    # Reps connect their own mailbox; Admin also holds the org-wide
    # admin scope so they can see + disconnect any rep's account.
    "email.accounts.manage",
    "email.accounts.admin",
    # Step 6 — template library. Admin/Owner can author + edit;
    # `email.read` is also granted so they can use templates from
    # compose.
    "email.read",
    "email.templates.manage",
    # Step 7 — sequence library + enroll. Admin authors and enrolls.
    "email.sequences.manage",
    "email.sequences.enroll",
    # tasks/template-library Step 3 — central multi-channel template
    # library. Admin can read / write / review (approve drafts) /
    # publish / submit-to-Meta-or-DLT. Junior roles get read only via
    # the Employee key list below.
    "templates.read",
    "templates.write",
    "templates.review",
    "templates.publish",
    "templates.submit_external",
    # tasks/automation-engine Step 3 — single-event trigger engine.
    # Admin authors triggers (write) + inspects run history (runs.read).
    # Read keeps the sidebar entry visible for read-only Employees.
    "automations.read",
    "automations.write",
    "automations.runs.read",
    # tasks/workflows Step 3 — multi-step branching workflows. Admin
    # gets all six keys: list/get (read), create/patch/archive
    # (write), draft→active (activate), clone, view analytics, view
    # diagnostics. Diagnostics exposes per-contact payload + rule
    # logic so it's a separate key + Owner/Admin only.
    "workflows.read",
    "workflows.write",
    "workflows.activate",
    "workflows.clone",
    "workflows.view_analytics",
    "workflows.view_diagnostics",
]


# Owner = Admin + the few keys only the workspace owner should hold.
# Curated (not ALL_KEYS) so pack-specific permissions don't leak into
# the sidebar of a vertical-pack-free org (template_id='base' or
# 'pending').
_CORE_OWNER_KEYS: list[str] = _CORE_ADMIN_KEYS + [
    "billing.refund",
    # Step 19 — subscription change / seats / cancel / checkout flows.
    # Granted to Owner only; Admin keeps `billing.read` for the legacy
    # invoice surface but cannot mutate plan / payment state.
    "billing.manage",
    "leads.scoring.manage",
]


_CORE_EMPLOYEE_KEYS: list[str] = [
    "contacts.read",
    "contacts.write",
    "leads.read",
    "leads.write",
    "activities.read",
    "activities.write",
    "tasks.read",
    "tasks.write",
    "appointments.read",
    "appointments.write",
    "walkins.read",
    "walkins.write",
    "walk_ins.read",
    "walk_ins.write",
    "catalog.read",
    "conversations.read",
    "conversations.write",
    "calls.read",
    "calls.write",
    "pipelines.read",
    # whatsapp-platform-upgrade Step 8 — Employees can READ templates
    # (they use them from compose) but cannot author or submit. Write +
    # submit stay Admin/Owner per the manager's RBAC spec.
    "whatsapp.templates.read",
    # Read-only so the dynamic forms on contacts / leads / walk-ins
    # can render their `custom_data` inputs. Mutation of the schema
    # stays Admin+Owner only via `custom_fields.write`.
    "custom_fields.read",
    "saved_views.use",
    # Employee can connect + disconnect their OWN mailbox; the
    # org-wide admin view is gated separately on `email.accounts.admin`
    # which Employee does not hold.
    "email.accounts.manage",
    # Step 6 — Employees CAN use saved templates from compose but
    # cannot author or edit them; `email.templates.manage` stays
    # Admin-only.
    "email.read",
    # Step 7 — Employees enroll their own leads into manager-built
    # sequences but cannot author/edit the sequence definitions.
    "email.sequences.enroll",
    # tasks/template-library Step 3 — Employees can READ templates
    # (so the editor's variable picker + the conversation composer's
    # template-pick action work) but cannot author, review, publish,
    # or submit externally. Owner/Admin holds the rest.
    "templates.read",
    # tasks/automation-engine Step 3 — Employees see the Settings →
    # Automations sidebar entry as read-only. Mutation + run-history
    # inspection stay Admin/Owner.
    "automations.read",
    # tasks/workflows Step 3 — Employees see the Workflows sidebar
    # entry + analytics dashboards as read-only. Mutation, activation,
    # clone, and the sensitive "why didn't this fire?" diagnostics
    # tool stay Admin/Owner.
    "workflows.read",
    "workflows.view_analytics",
]


# Optional templates — surfaced on the Roles page as "Add from template"
# presets. Not auto-installed; an Owner clicks to instantiate. Permission
# sets are curated to the role's job: a Sales Manager runs the funnel and
# the team; a Support Agent talks to customers but doesn't touch the
# pipeline shape or billing.
_CORE_SALES_MANAGER_KEYS: list[str] = [
    "contacts.read",
    "contacts.write",
    "contacts.reassign",
    "leads.read",
    "leads.write",
    "leads.reassign",
    "leads.export",
    "appointments.read",
    "appointments.write",
    "appointments.reassign",
    "walkins.read",
    "walkins.write",
    "walkins.reassign",
    "walk_ins.read",
    "walk_ins.write",
    "tasks.read",
    "tasks.write",
    "activities.read",
    "activities.write",
    "pipelines.read",
    "pipelines.manage",
    "calls.read",
    "calls.write",
    "calls.outcomes.manage",
    "campaigns.read",
    "campaigns.write",
    "campaigns.send",
    "reviews.read",
    "catalog.read",
    "staff.read",
    "users.read",
    "custom_fields.read",
    "saved_views.use",
    "email.accounts.manage",
    # Step 6 — Sales Manager runs the sales motion; authoring
    # outreach templates is squarely within scope.
    "email.read",
    "email.templates.manage",
    # Step 7 — Sales Manager authors sequences and enrolls leads.
    "email.sequences.manage",
    "email.sequences.enroll",
]


_CORE_SUPPORT_AGENT_KEYS: list[str] = [
    "contacts.read",
    "contacts.write",
    "conversations.read",
    "conversations.write",
    "calls.read",
    "calls.write",
    "reviews.read",
    "reviews.write",
    "tasks.read",
    "tasks.write",
    "activities.read",
    "activities.write",
    "catalog.read",
    "walkins.read",
    "walk_ins.read",
    "leads.read",
    "custom_fields.read",
    "saved_views.use",
    "email.accounts.manage",
    # Step 6 — Support agents talk to customers; reading templates
    # to use from compose is in scope. Authoring is not.
    "email.read",
]


@dataclass(frozen=True)
class RoleTemplate:
    key: str
    name: str
    is_system: bool
    is_owner: bool
    permission_keys: list[str] | str
    description: str
    auto_install_on_org_create: bool = True
    extra_keys: list[str] = field(default_factory=list)


ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    "owner": RoleTemplate(
        key="owner",
        name="Owner",
        is_system=True,
        is_owner=True,
        permission_keys=_CORE_OWNER_KEYS,
        description="Full workspace control. Cannot be edited or deleted.",
    ),
    "admin": RoleTemplate(
        key="admin",
        name="Admin",
        is_system=False,
        is_owner=False,
        permission_keys=_CORE_ADMIN_KEYS,
        description=(
            "Manage users, leads, contacts, deals; view reports; "
            "configure settings. No billing refund or ownership transfer."
        ),
    ),
    "employee": RoleTemplate(
        key="employee",
        name="Employee",
        is_system=False,
        is_owner=False,
        permission_keys=_CORE_EMPLOYEE_KEYS,
        description=(
            "View assigned leads; manage own tasks/contacts/deals; "
            "limited reports. No user management."
        ),
    ),
    "sales_manager": RoleTemplate(
        key="sales_manager",
        name="Sales Manager",
        is_system=False,
        is_owner=False,
        permission_keys=_CORE_SALES_MANAGER_KEYS,
        description=(
            "Run the sales funnel: leads, pipelines, calls, campaigns, "
            "appointments. View staff + users. No user management or billing."
        ),
        auto_install_on_org_create=False,
    ),
    "support_agent": RoleTemplate(
        key="support_agent",
        name="Support Agent",
        is_system=False,
        is_owner=False,
        permission_keys=_CORE_SUPPORT_AGENT_KEYS,
        description=(
            "Talk to customers: conversations, calls, reviews. "
            "Read-only on leads and catalog. No pipeline or billing access."
        ),
        auto_install_on_org_create=False,
    ),
}


async def _resolve_keys(session: AsyncSession, template: RoleTemplate) -> list[uuid.UUID]:
    """Map a template's permission_keys list to ids.

    Skips keys that aren't in the live registry (rather than raising)
    so a pack that isn't loaded today doesn't break a self-signup.
    Unknown keys are silently ignored — the role just doesn't get them.
    """
    keys = list(template.permission_keys)
    if not keys:
        return []
    rows = (
        await session.execute(select(Permission.id, Permission.key).where(Permission.key.in_(keys)))
    ).all()
    found = {r.key: r.id for r in rows}
    return [found[k] for k in keys if k in found]


async def _install_one(session: AsyncSession, *, org_id: uuid.UUID, template: RoleTemplate) -> Role:
    if template.is_owner:
        existing_owner = (
            await session.execute(
                select(Role.id).where(
                    Role.org_id == org_id, Role.is_system.is_(True), Role.name == "Owner"
                )
            )
        ).scalar_one_or_none()
        if existing_owner is not None:
            raise OwnerAlreadyExists(f"org {org_id} already has an Owner role")

    existing = (
        await session.execute(select(Role).where(Role.org_id == org_id, Role.name == template.name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    role = Role(org_id=org_id, name=template.name, is_system=template.is_system)
    session.add(role)
    await session.flush()

    permission_ids = await _resolve_keys(session, template)
    if permission_ids:
        await session.execute(
            pg_insert(RolePermission)
            .values([{"role_id": role.id, "permission_id": pid} for pid in permission_ids])
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )

    return role


async def installed_template_names(session: AsyncSession, org_id: uuid.UUID) -> set[str]:
    """Names of `roles` rows in this org that match any template name.

    Used by the Roles page to mark templates as `installed=true` when
    the org already has a same-named role. Match is by `name` because
    that's what we wrote when the template was instantiated; the
    `template_key` isn't stored on the role row.
    """
    template_names = {t.name for t in ROLE_TEMPLATES.values()}
    rows = (
        await session.execute(
            select(Role.name).where(Role.org_id == org_id, Role.name.in_(template_names))
        )
    ).all()
    return {r.name for r in rows}


async def install(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_keys: list[str] | None = None,
) -> dict[str, Role]:
    """Install the named templates into the given org.

    `template_keys=None` installs every template with
    `auto_install_on_org_create=True` (Owner + Admin + Employee for the
    default registry). Idempotent — calling again returns the existing
    rows without writing. All inserts run on the caller's session; the
    caller manages the outer transaction.

    Returns a `{template_key: Role}` map so the signup flow can pluck
    out the Owner row to assign on `tbl_organization_members.role_id`.
    """
    if template_keys is None:
        template_keys = [k for k, t in ROLE_TEMPLATES.items() if t.auto_install_on_org_create]

    installed: dict[str, Role] = {}
    for key in template_keys:
        template = ROLE_TEMPLATES.get(key)
        if template is None:
            raise UnknownPermissionKey(f"unknown role template: {key!r}")
        installed[key] = await _install_one(session, org_id=org_id, template=template)
    return installed
