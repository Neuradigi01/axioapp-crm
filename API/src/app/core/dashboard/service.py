"""Dashboard summary assembler.

Builds the `{ greeting, scope, cards, recent_activity, upcoming_appointments }`
payload from the existing core models. No raw SQL; all queries go
through the layered ORM so the `TenantScoped` auto-filter keeps each
read within the caller's org.

`scope` is decided off the caller's permission set:
  - has `users.read`  → org-wide cards
  - otherwise         → personal cards filtered by `assigned_to_id = caller`

Adding a card later is a one-line entry in `_assemble_org_cards()` or
`_assemble_personal_cards()` plus a matching frontend template branch
on `format`. No new modules, no new permission keys.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.audit.models import AuditLog
from src.app.core.calls.models import Call
from src.app.core.contacts.models import Contact
from src.app.core.dashboard.schemas import (
    ActivityItem,
    DashboardCard,
    DashboardSummary,
    Greeting,
    UpcomingAppointment,
)
from src.app.core.invitations.models import Invitation
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import Role
from src.app.core.permissions.service import list_permissions_for_role
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User, UserInfo


# Action prefixes that show up on the dashboard's recent-activity feed.
# Everything else (login, password change, access denied, self-profile
# edits) is intentionally hidden — those are security/audit signals,
# not user-relevant activity.
_ACTIVITY_INCLUDE_PREFIXES = (
    "leads.",
    "contacts.",
    "appointments.",
    "tasks.",
    "calls.",
    "walkins.",
    "walk_ins.",
    "reviews.",
)
_ACTIVITY_INCLUDE_EXACT = {
    "invitations.sent",
    "invitations.accepted",
    "roles.assigned_to_user",
    "ownership.transferred",
}


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 of the current ISO week, in UTC."""
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return midnight - timedelta(days=now.weekday())


async def _has_users_read(session: AsyncSession, role_id: uuid.UUID) -> bool:
    granted = {p.key for p in await list_permissions_for_role(session, role_id)}
    return "users.read" in granted


async def _greeting(session: AsyncSession, user: User) -> Greeting:
    info = user.info
    first = (info.first_name if info else "") or ""
    org = (
        await session.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
    ).scalar_one()
    role = (
        await session.execute(
            select(Role).where(Role.id == user.role_id)
        )
    ).scalar_one_or_none()
    return Greeting(
        first_name=first or "there",
        role_name=role.name if role else "",
        org_name=org.name,
    )


async def _assemble_org_cards(
    session: AsyncSession, org_id: uuid.UUID, now: datetime
) -> list[DashboardCard]:
    today = now.date()
    week_start = _week_start(now)

    cards: list[DashboardCard] = []

    leads_new_today = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                func.date(Lead.created_at) == today,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="leads.new_today",
            label="New leads today",
            value=int(leads_new_today),
            format="number",
            link="/user/leads",
        )
    )

    pipeline_value = (
        await session.execute(
            select(func.coalesce(func.sum(Lead.budget), 0)).where(
                Lead.org_id == org_id,
                Lead.status == LeadStatus.active,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="leads.pipeline_value",
            label="Total pipeline value",
            value=float(pipeline_value or 0),
            format="currency",
            link="/user/leads",
        )
    )

    tasks_open = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.status == TaskStatus.open,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="tasks.open_count",
            label="Open tasks (team)",
            value=int(tasks_open),
            format="number",
            link="/user/tasks",
        )
    )

    appts_today = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.org_id == org_id,
                func.date(Appointment.scheduled_at) == today,
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="appointments.today",
            label="Today's appointments",
            value=int(appts_today),
            format="number",
            link="/user/appointments",
        )
    )

    calls_this_week = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.started_at >= week_start,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="calls.this_week",
            label="Calls this week",
            value=int(calls_this_week),
            format="number",
            link="/user/calls",
        )
    )

    contacts_total = (
        await session.execute(
            select(func.count(Contact.id)).where(Contact.org_id == org_id)
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="contacts.total",
            label="Total contacts",
            value=int(contacts_total),
            format="number",
            link="/user/contacts",
        )
    )

    # Conversion rate over the last 30 days: won / (won + lost) * 100.
    # NULLIF on the denominator collapses the zero-leads case to NULL,
    # which COALESCE turns into 0 so the card is always renderable.
    thirty_days_ago = now - timedelta(days=30)
    closed_filter = (Lead.status == LeadStatus.won) | (
        Lead.status == LeadStatus.lost
    )
    won_count = func.sum(case((Lead.status == LeadStatus.won, 1), else_=0))
    closed_count = func.sum(case((closed_filter, 1), else_=0))
    conversion = (
        await session.execute(
            select(
                func.coalesce(
                    won_count * 100.0 / func.nullif(closed_count, 0), 0
                )
            ).where(
                Lead.org_id == org_id,
                Lead.updated_at >= thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="conversion.rate",
            label="Conversion rate (30d)",
            value=round(float(conversion or 0), 1),
            format="percent",
            link="/user/leads",
        )
    )

    # Top performers — leads created this week, grouped by assignee,
    # top 3. Joins through `tbl_user_info` for the display name. Skips
    # the card entirely when nobody has created a lead this week to
    # avoid an empty list with no signal.
    perf_rows = (
        await session.execute(
            select(
                UserInfo.first_name,
                UserInfo.last_name,
                func.count(Lead.id).label("c"),
            )
            .select_from(Lead)
            .join(User, User.legacy_uuid == Lead.assigned_to_id)
            .join(UserInfo, UserInfo.member_id == User.id)
            .where(
                Lead.org_id == org_id,
                Lead.created_at >= week_start,
                Lead.assigned_to_id.is_not(None),
            )
            .group_by(UserInfo.first_name, UserInfo.last_name)
            .order_by(func.count(Lead.id).desc())
            .limit(3)
        )
    ).all()
    if perf_rows:
        cards.append(
            DashboardCard(
                key="top_performers",
                label="Top performers (this week)",
                value=[
                    {
                        "name": f"{r.first_name or ''} {r.last_name or ''}".strip()
                        or "Unknown",
                        "count": int(r.c),
                    }
                    for r in perf_rows
                ],
                format="leaderboard",
                link="/user/staff",
            )
        )

    return cards


async def _assemble_personal_cards(
    session: AsyncSession, org_id: uuid.UUID, user_uuid: uuid.UUID, now: datetime
) -> list[DashboardCard]:
    today = now.date()
    week_start = _week_start(now)

    cards: list[DashboardCard] = []

    my_tasks = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.assigned_to_id == user_uuid,
                Task.status == TaskStatus.open,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="tasks.my_open",
            label="My open tasks",
            value=int(my_tasks),
            format="number",
            link="/user/tasks",
        )
    )

    my_leads = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="leads.my_count",
            label="My leads",
            value=int(my_leads),
            format="number",
            link="/user/leads",
        )
    )

    my_appts_today = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.org_id == org_id,
                Appointment.assigned_to_id == user_uuid,
                func.date(Appointment.scheduled_at) == today,
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="appointments.my_today",
            label="My appointments today",
            value=int(my_appts_today),
            format="number",
            link="/user/appointments",
        )
    )

    my_calls = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.assigned_to_id == user_uuid,
                Call.started_at >= week_start,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="calls.my_this_week",
            label="My calls this week",
            value=int(my_calls),
            format="number",
            link="/user/calls",
        )
    )

    thirty_days_ago = now - timedelta(days=30)
    closed_filter = (Lead.status == LeadStatus.won) | (
        Lead.status == LeadStatus.lost
    )
    won_count = func.sum(case((Lead.status == LeadStatus.won, 1), else_=0))
    closed_count = func.sum(case((closed_filter, 1), else_=0))
    my_conversion = (
        await session.execute(
            select(
                func.coalesce(
                    won_count * 100.0 / func.nullif(closed_count, 0), 0
                )
            ).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
                Lead.updated_at >= thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        DashboardCard(
            key="conversion.my_rate",
            label="My conversion rate (30d)",
            value=round(float(my_conversion or 0), 1),
            format="percent",
            link="/user/leads",
        )
    )

    # `contacts` has no owner/assigned column today — per the spec we
    # omit the `contacts.my_count` card rather than render a misleading
    # zero or fall back to created_by (which doesn't exist).

    return cards


async def _recent_activity(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_uuid: uuid.UUID,
    personal_only: bool,
) -> list[ActivityItem]:
    """Last ~10 user-relevant audit rows, with entity labels resolved.

    For personal scope, restricts to actions the caller performed
    (`audit_logs.user_id = caller_uuid`). For org scope, returns all
    actions the org saw. Login / access-denied / password-change events
    are filtered out entirely either way — those are security signals,
    not "activity."
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(40)
    )
    if personal_only:
        stmt = stmt.where(AuditLog.user_id == caller_uuid)

    rows = (await session.execute(stmt)).scalars().all()

    visible: list[AuditLog] = []
    for r in rows:
        if r.action in _ACTIVITY_INCLUDE_EXACT or any(
            r.action.startswith(p) for p in _ACTIVITY_INCLUDE_PREFIXES
        ):
            visible.append(r)
        if len(visible) >= 10:
            break

    # Batch-resolve entity labels by type so we don't N+1 over the
    # 10-row window. Each block does one SELECT WHERE id IN (...).
    ids_by_type: dict[str, set[uuid.UUID]] = {}
    for r in visible:
        if r.entity_type and r.entity_id:
            ids_by_type.setdefault(r.entity_type, set()).add(r.entity_id)

    label_map: dict[tuple[str, uuid.UUID], str] = {}

    if ids := ids_by_type.get("lead"):
        result = await session.execute(
            select(Lead.id, Contact.full_name)
            .join(Contact, Contact.id == Lead.contact_id)
            .where(Lead.id.in_(ids))
        )
        for lid, name in result.all():
            label_map[("lead", lid)] = name or "lead"

    if ids := ids_by_type.get("contact"):
        result = await session.execute(
            select(Contact.id, Contact.full_name).where(Contact.id.in_(ids))
        )
        for cid, name in result.all():
            label_map[("contact", cid)] = name or "contact"

    if ids := ids_by_type.get("appointment"):
        result = await session.execute(
            select(Appointment.id, Appointment.title).where(Appointment.id.in_(ids))
        )
        for aid, title in result.all():
            label_map[("appointment", aid)] = title or "appointment"

    if ids := ids_by_type.get("task"):
        result = await session.execute(
            select(Task.id, Task.title).where(Task.id.in_(ids))
        )
        for tid, title in result.all():
            label_map[("task", tid)] = title or "task"

    if ids := ids_by_type.get("invitation"):
        result = await session.execute(
            select(Invitation.id, Invitation.email).where(Invitation.id.in_(ids))
        )
        for iid, email in result.all():
            label_map[("invitation", iid)] = email or "invitation"

    # Resolve actor names: one batch lookup over the caller-union.
    actor_ids = {r.user_id for r in visible if r.user_id}
    actor_map: dict[uuid.UUID, str] = {}
    if actor_ids:
        result = await session.execute(
            select(User.legacy_uuid, UserInfo.first_name, UserInfo.last_name)
            .join(UserInfo, UserInfo.member_id == User.id)
            .where(User.legacy_uuid.in_(actor_ids))
        )
        for uid, first, last in result.all():
            actor_map[uid] = (
                f"{first or ''} {last or ''}".strip() or "Someone"
            )

    items: list[ActivityItem] = []
    for r in visible:
        if r.user_id and r.user_id == caller_uuid:
            actor = "You"
        elif r.user_id:
            actor = actor_map.get(r.user_id, "Someone")
        else:
            actor = "System"

        if r.entity_type and r.entity_id:
            label = label_map.get(
                (r.entity_type, r.entity_id),
                f"{r.entity_type}:{str(r.entity_id)[:8]}",
            )
        else:
            label = r.entity_type or "—"

        items.append(
            ActivityItem(
                action=r.action,
                entity_label=label,
                actor_name=actor,
                at=r.created_at,
            )
        )
    return items


async def _upcoming_appointments(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_uuid: uuid.UUID | None,
    now: datetime,
) -> list[UpcomingAppointment]:
    """Next 5 scheduled appointments. Personal scope restricts to caller."""
    stmt = (
        select(Appointment.id, Appointment.title, Appointment.scheduled_at, Contact.full_name)
        .join(Contact, Contact.id == Appointment.contact_id)
        .where(
            Appointment.org_id == org_id,
            Appointment.scheduled_at > now,
            Appointment.status == AppointmentStatus.scheduled,
        )
        .order_by(Appointment.scheduled_at.asc())
        .limit(5)
    )
    if user_uuid is not None:
        stmt = stmt.where(Appointment.assigned_to_id == user_uuid)

    rows = (await session.execute(stmt)).all()
    return [
        UpcomingAppointment(
            id=row.id,
            title=row.title,
            starts_at=row.scheduled_at,
            with_contact_name=row.full_name or "",
        )
        for row in rows
    ]


async def get_summary(session: AsyncSession, caller: User) -> DashboardSummary:
    org_id = caller.org_id
    if org_id is None:
        # An authenticated user with no active membership is a bug
        # higher up the stack; degrade to an empty payload here rather
        # than 500-ing the dashboard.
        return DashboardSummary(
            greeting=Greeting(first_name="there", role_name="", org_name=""),
            scope="personal",
            cards=[],
            recent_activity=[],
            upcoming_appointments=[],
        )

    now = datetime.now(timezone.utc)
    greeting = await _greeting(session, caller)

    is_org_scope = await _has_users_read(session, caller.role_id)
    caller_uuid = caller.legacy_uuid

    if is_org_scope:
        cards = await _assemble_org_cards(session, org_id, now)
        recent = await _recent_activity(
            session, org_id, caller_uuid, personal_only=False
        )
        upcoming = await _upcoming_appointments(session, org_id, None, now)
        scope = "org"
    else:
        cards = await _assemble_personal_cards(session, org_id, caller_uuid, now)
        recent = await _recent_activity(
            session, org_id, caller_uuid, personal_only=True
        )
        upcoming = await _upcoming_appointments(session, org_id, caller_uuid, now)
        scope = "personal"

    return DashboardSummary(
        greeting=greeting,
        scope=scope,
        cards=cards,
        recent_activity=recent,
        upcoming_appointments=upcoming,
    )
