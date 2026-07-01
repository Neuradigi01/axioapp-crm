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
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.audit.models import AuditLog
from src.app.core.calls.models import Call
from src.app.core.contacts.models import Contact
from src.app.core.dashboard import data_access as _da
from src.app.core.dashboard.schemas import (
    ActivityItem,
    DashboardCard,
    DashboardFunnelResponse,
    DashboardSummary,
    DashboardTrendPoint,
    DashboardTrendResponse,
    FollowupAssignedTo,
    FollowupBucket,
    FollowupItem,
    FollowupLinkedEntity,
    FollowupsResponse,
    FunnelStageBucket,
    Greeting,
    TrendMetric,
    TrendRange,
    UpcomingAppointment,
)
from src.app.core.invitations.models import Invitation
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import Role
from src.app.core.permissions.service import list_permissions_for_role
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.tenants import data_access
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
    midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return midnight - timedelta(days=now.weekday())


def _delta(current: float, previous: float) -> tuple[float, Literal["up", "down", "flat"]]:
    """Return `(signed_pct, direction)` for a current/previous pair.

    Zero baseline collapses to `+100` when current > 0 so the frontend
    still renders a meaningful pill; both zero collapses to flat. The
    0.05 % deadband on direction prevents noisy near-zero arrows.
    """
    if previous == 0:
        if current > 0:
            return (100.0, "up")
        return (0.0, "flat")
    pct = round((current - previous) / previous * 100.0, 1)
    if pct > 0.05:
        direction: Literal["up", "down", "flat"] = "up"
    elif pct < -0.05:
        direction = "down"
    else:
        direction = "flat"
    return (pct, direction)


def _scalar_card(
    *,
    key: str,
    label: str,
    current: float | int,
    previous: float | int,
    format: Literal["number", "currency", "percent"],
    link: str | None,
) -> DashboardCard:
    """Build a scalar KPI card with prior-period delta fields populated.

    Currency / number / percent share the same delta-pill rendering on
    the frontend so a single helper covers all three.
    """
    pct, direction = _delta(float(current), float(previous))
    return DashboardCard(
        key=key,
        label=label,
        value=current,
        format=format,
        link=link,
        previous_value=previous,
        delta_pct=pct,
        delta_direction=direction,
    )


async def _has_users_read(session: AsyncSession, role_id: uuid.UUID) -> bool:
    granted = {p.key for p in await list_permissions_for_role(session, role_id)}
    return "users.read" in granted


async def _greeting(session: AsyncSession, user: User) -> Greeting:
    info = user.info
    first = (info.first_name if info else "") or ""
    org = await data_access.get_organization_by_id(session, user.org_id)
    assert org is not None  # authed user implies their org exists
    role = (await session.execute(select(Role).where(Role.id == user.role_id))).scalar_one_or_none()
    return Greeting(
        first_name=first or "there",
        role_name=role.name if role else "",
        org_name=org.name,
    )


async def _assemble_org_cards(
    session: AsyncSession, org_id: uuid.UUID, now: datetime
) -> list[DashboardCard]:
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_start = _week_start(now)
    prev_week_start = week_start - timedelta(days=7)
    prev_week_cutoff = prev_week_start + (now - week_start)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    cards: list[DashboardCard] = []

    # leads.new_today  vs  leads created yesterday
    leads_new_today = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                func.date(Lead.created_at) == today,
            )
        )
    ).scalar_one()
    leads_new_prev = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                func.date(Lead.created_at) == yesterday,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="leads.new_today",
            label="New leads today",
            current=int(leads_new_today),
            previous=int(leads_new_prev),
            format="number",
            link="/user/leads",
        )
    )

    # leads.pipeline_value  vs  pipeline as-of 30d ago.
    # No status-history table exists, so "active 30d ago" approximates
    # via `created_at <= 30d ago AND status == active`. Undercounts
    # leads that have since been won/lost (they were active then but
    # not now). Acceptable for a trend arrow; documented to keep the
    # assumption visible.
    pipeline_value = (
        await session.execute(
            select(func.coalesce(func.sum(Lead.budget), 0)).where(
                Lead.org_id == org_id,
                Lead.status == LeadStatus.active,
            )
        )
    ).scalar_one()
    pipeline_value_prev = (
        await session.execute(
            select(func.coalesce(func.sum(Lead.budget), 0)).where(
                Lead.org_id == org_id,
                Lead.status == LeadStatus.active,
                Lead.created_at <= thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="leads.pipeline_value",
            label="Total pipeline value",
            current=float(pipeline_value or 0),
            previous=float(pipeline_value_prev or 0),
            format="currency",
            link="/user/leads",
        )
    )

    # tasks.open_count  vs  snapshot of open tasks as-of 7d ago.
    # `Task` has no `closed_at`; we approximate by counting tasks that
    # existed 7d ago AND were either still open or were closed within
    # the last 7d (so they were open then). `updated_at` proxies the
    # status-change timestamp because the only column that bumps on
    # close is `updated_at`.
    tasks_open = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.status == TaskStatus.open,
            )
        )
    ).scalar_one()
    tasks_open_prev = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.created_at <= seven_days_ago,
                or_(
                    Task.status == TaskStatus.open,
                    Task.updated_at > seven_days_ago,
                ),
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="tasks.open_count",
            label="Open tasks (team)",
            current=int(tasks_open),
            previous=int(tasks_open_prev),
            format="number",
            link="/user/tasks",
        )
    )

    # appointments.today  vs  yesterday
    appts_today = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.org_id == org_id,
                func.date(Appointment.scheduled_at) == today,
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
    ).scalar_one()
    appts_prev = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.org_id == org_id,
                func.date(Appointment.scheduled_at) == yesterday,
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="appointments.today",
            label="Today's appointments",
            current=int(appts_today),
            previous=int(appts_prev),
            format="number",
            link="/user/appointments",
        )
    )

    # calls.this_week  vs  same week-to-date offset in the previous
    # week (so on Wed at 3pm we compare Mon 00:00 → Wed 3pm vs the
    # equivalent range one week earlier).
    calls_this_week = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.started_at >= week_start,
            )
        )
    ).scalar_one()
    calls_prev_week = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.started_at >= prev_week_start,
                Call.started_at < prev_week_cutoff,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="calls.this_week",
            label="Calls this week",
            current=int(calls_this_week),
            previous=int(calls_prev_week),
            format="number",
            link="/user/calls",
        )
    )

    # contacts.total (cumulative)  vs  cumulative count as-of 30d ago
    contacts_total = (
        await session.execute(select(func.count(Contact.id)).where(Contact.org_id == org_id))
    ).scalar_one()
    contacts_prev = (
        await session.execute(
            select(func.count(Contact.id)).where(
                Contact.org_id == org_id,
                Contact.created_at < thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="contacts.total",
            label="Total contacts",
            current=int(contacts_total),
            previous=int(contacts_prev),
            format="number",
            link="/user/contacts",
        )
    )

    # Conversion rate over the last 30 days: won / (won + lost) * 100.
    # NULLIF on the denominator collapses the zero-leads case to NULL,
    # which COALESCE turns into 0 so the card is always renderable.
    # Prior period is the 30 days before that.
    closed_filter = (Lead.status == LeadStatus.won) | (Lead.status == LeadStatus.lost)
    won_count_expr = func.sum(case((Lead.status == LeadStatus.won, 1), else_=0))
    closed_count_expr = func.sum(case((closed_filter, 1), else_=0))
    conversion = (
        await session.execute(
            select(
                func.coalesce(won_count_expr * 100.0 / func.nullif(closed_count_expr, 0), 0)
            ).where(
                Lead.org_id == org_id,
                Lead.updated_at >= thirty_days_ago,
            )
        )
    ).scalar_one()
    conversion_prev = (
        await session.execute(
            select(
                func.coalesce(won_count_expr * 100.0 / func.nullif(closed_count_expr, 0), 0)
            ).where(
                Lead.org_id == org_id,
                Lead.updated_at >= sixty_days_ago,
                Lead.updated_at < thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="conversion.rate",
            label="Conversion rate (30d)",
            current=round(float(conversion or 0), 1),
            previous=round(float(conversion_prev or 0), 1),
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
                        "name": f"{r.first_name or ''} {r.last_name or ''}".strip() or "Unknown",
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
    prev_week_start = week_start - timedelta(days=7)
    prev_week_cutoff = prev_week_start + (now - week_start)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    cards: list[DashboardCard] = []

    # tasks.my_open  vs  snapshot of own open tasks as-of 7d ago.
    # Same approximation rule as the org card: open then = created
    # before 7d ago AND (still open OR closed within the last 7d).
    my_tasks = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.assigned_to_id == user_uuid,
                Task.status == TaskStatus.open,
            )
        )
    ).scalar_one()
    my_tasks_prev = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.org_id == org_id,
                Task.assigned_to_id == user_uuid,
                Task.created_at <= seven_days_ago,
                or_(
                    Task.status == TaskStatus.open,
                    Task.updated_at > seven_days_ago,
                ),
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="tasks.my_open",
            label="My open tasks",
            current=int(my_tasks),
            previous=int(my_tasks_prev),
            format="number",
            link="/user/tasks",
        )
    )

    # leads.my_count (cumulative)  vs  cumulative as-of 30d ago
    my_leads = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
            )
        )
    ).scalar_one()
    my_leads_prev = (
        await session.execute(
            select(func.count(Lead.id)).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
                Lead.created_at < thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="leads.my_count",
            label="My leads",
            current=int(my_leads),
            previous=int(my_leads_prev),
            format="number",
            link="/user/leads",
        )
    )

    # appointments.my_today  vs  yesterday
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
    my_appts_prev = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.org_id == org_id,
                Appointment.assigned_to_id == user_uuid,
                func.date(Appointment.scheduled_at) == today - timedelta(days=1),
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="appointments.my_today",
            label="My appointments today",
            current=int(my_appts_today),
            previous=int(my_appts_prev),
            format="number",
            link="/user/appointments",
        )
    )

    # calls.my_this_week  vs  same week-to-date offset in the prior week
    my_calls = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.assigned_to_id == user_uuid,
                Call.started_at >= week_start,
            )
        )
    ).scalar_one()
    my_calls_prev = (
        await session.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.assigned_to_id == user_uuid,
                Call.started_at >= prev_week_start,
                Call.started_at < prev_week_cutoff,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="calls.my_this_week",
            label="My calls this week",
            current=int(my_calls),
            previous=int(my_calls_prev),
            format="number",
            link="/user/calls",
        )
    )

    # conversion.my_rate (last 30d)  vs  the 30d before
    closed_filter = (Lead.status == LeadStatus.won) | (Lead.status == LeadStatus.lost)
    won_count_expr = func.sum(case((Lead.status == LeadStatus.won, 1), else_=0))
    closed_count_expr = func.sum(case((closed_filter, 1), else_=0))
    my_conversion = (
        await session.execute(
            select(
                func.coalesce(won_count_expr * 100.0 / func.nullif(closed_count_expr, 0), 0)
            ).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
                Lead.updated_at >= thirty_days_ago,
            )
        )
    ).scalar_one()
    my_conversion_prev = (
        await session.execute(
            select(
                func.coalesce(won_count_expr * 100.0 / func.nullif(closed_count_expr, 0), 0)
            ).where(
                Lead.org_id == org_id,
                Lead.assigned_to_id == user_uuid,
                Lead.updated_at >= sixty_days_ago,
                Lead.updated_at < thirty_days_ago,
            )
        )
    ).scalar_one()
    cards.append(
        _scalar_card(
            key="conversion.my_rate",
            label="My conversion rate (30d)",
            current=round(float(my_conversion or 0), 1),
            previous=round(float(my_conversion_prev or 0), 1),
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
        result = await session.execute(select(Task.id, Task.title).where(Task.id.in_(ids)))
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
            actor_map[uid] = f"{first or ''} {last or ''}".strip() or "Someone"

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

    now = datetime.now(UTC)
    greeting = await _greeting(session, caller)

    is_org_scope = await _has_users_read(session, caller.role_id)
    caller_uuid = caller.legacy_uuid

    if is_org_scope:
        cards = await _assemble_org_cards(session, org_id, now)
        recent = await _recent_activity(session, org_id, caller_uuid, personal_only=False)
        upcoming = await _upcoming_appointments(session, org_id, None, now)
        scope = "org"
    else:
        cards = await _assemble_personal_cards(session, org_id, caller_uuid, now)
        recent = await _recent_activity(session, org_id, caller_uuid, personal_only=True)
        upcoming = await _upcoming_appointments(session, org_id, caller_uuid, now)
        scope = "personal"

    return DashboardSummary(
        greeting=greeting,
        scope=scope,
        cards=cards,
        recent_activity=recent,
        upcoming_appointments=upcoming,
    )


_RANGE_DAYS: dict[TrendRange, int] = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}


async def assemble_trend(
    session: AsyncSession,
    caller: User,
    metric: TrendMetric,
    range_str: TrendRange,
) -> DashboardTrendResponse:
    """Build a day-bucketed time series for `metric` over `range_str`.

    Same scope rule as `get_summary`: callers with `users.read` get
    org-wide buckets, everyone else gets `assigned_to_id = caller`
    personal buckets. The series is always exactly `range_days` points,
    zero-filled for missing buckets so the frontend never sees gaps.

    `pipeline_value` is intentionally simplified to "sum of `budget` for
    leads created in the bucket" rather than a running-snapshot of
    active pipeline — the latter requires a status-history table we
    don't have, and the daily-creation sum is what a v1 trend chart
    needs.
    """
    org_id = caller.org_id
    range_days = _RANGE_DAYS[range_str]
    today = datetime.now(UTC).date()
    start = today - timedelta(days=range_days - 1)

    if org_id is None:
        # Same defensive shape as `get_summary`: no membership → empty
        # but well-formed series.
        return DashboardTrendResponse(
            metric=metric,
            range=range_str,
            scope="personal",
            points=[
                DashboardTrendPoint(date=start + timedelta(days=i), value=0.0)
                for i in range(range_days)
            ],
        )

    is_org_scope = await _has_users_read(session, caller.role_id)
    scope: Literal["org", "personal"] = "org" if is_org_scope else "personal"
    caller_uuid = caller.legacy_uuid

    if metric == "leads_created":
        ts_col = Lead.created_at
        value_expr = func.count(Lead.id)
        scope_col = Lead.assigned_to_id
        org_col = Lead.org_id
    elif metric == "pipeline_value":
        ts_col = Lead.created_at
        value_expr = func.coalesce(func.sum(Lead.budget), 0)
        scope_col = Lead.assigned_to_id
        org_col = Lead.org_id
    elif metric == "calls":
        ts_col = Call.started_at
        value_expr = func.count(Call.id)
        scope_col = Call.assigned_to_id
        org_col = Call.org_id
    else:  # metric == "appointments"
        ts_col = Appointment.scheduled_at
        value_expr = func.count(Appointment.id)
        scope_col = Appointment.assigned_to_id
        org_col = Appointment.org_id

    bucket = func.date(ts_col).label("bucket")
    stmt = (
        select(bucket, value_expr.label("v"))
        .where(org_col == org_id, ts_col >= start)
        .group_by(bucket)
        .order_by(bucket.asc())
    )
    if not is_org_scope:
        stmt = stmt.where(scope_col == caller_uuid)

    rows = (await session.execute(stmt)).all()
    by_date: dict[date, float] = {row.bucket: float(row.v or 0) for row in rows}

    points = [
        DashboardTrendPoint(
            date=(d := start + timedelta(days=i)),
            value=by_date.get(d, 0.0),
        )
        for i in range(range_days)
    ]
    return DashboardTrendResponse(
        metric=metric,
        range=range_str,
        scope=scope,
        points=points,
    )


_LEADS_PIPELINE_KEY = "leads"


async def assemble_funnel(
    session: AsyncSession,
    caller: User,
    range_str: TrendRange,
) -> DashboardFunnelResponse:
    """Build a per-stage funnel snapshot of leads created in the range.

    Same scope rule as `get_summary`: callers with `users.read` get
    org-wide counts, everyone else gets `assigned_to_id = caller`
    personal counts. The `stages` list is deterministic — every
    non-terminal stage of the org's leads pipeline appears in
    `display_order` order, zero-filled when no leads landed there.

    `won_count` / `lost_count` are reported separately off the
    terminal `Lead.status` enum so the frontend can render the
    funnel-mouth (stages) and the win/loss outcomes side by side
    without double-counting. `total_leads_in_range` is the sum of
    everything so labels can render "% of total" without an extra
    request.

    Leads link to stages by `pipeline_stage` (the stage's stable
    text `key`), not by stage UUID — matching the pipelines engine
    convention. Soft-deleted stages do not exist as a concept here
    (no `is_active` column), so every stage of the leads pipeline is
    considered active.
    """
    org_id = caller.org_id
    range_days = _RANGE_DAYS[range_str]
    now = datetime.now(UTC)
    start = now - timedelta(days=range_days)

    if org_id is None:
        return DashboardFunnelResponse(
            range=range_str,
            scope="personal",
            total_leads_in_range=0,
            stages=[],
            won_count=0,
            lost_count=0,
        )

    is_org_scope = await _has_users_read(session, caller.role_id)
    scope: Literal["org", "personal"] = "org" if is_org_scope else "personal"
    caller_uuid = caller.legacy_uuid

    # Non-terminal stages of the org's leads pipeline, deterministic
    # left-to-right via `display_order`. Won/lost stages are excluded
    # from the funnel list because their counts surface separately via
    # `Lead.status` (won/lost are terminal outcomes, not funnel steps).
    stage_rows = (
        await session.execute(
            select(
                PipelineStage.id,
                PipelineStage.key,
                PipelineStage.name,
                PipelineStage.display_order,
            )
            .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
            .where(
                PipelineStage.org_id == org_id,
                Pipeline.org_id == org_id,
                Pipeline.key == _LEADS_PIPELINE_KEY,
                PipelineStage.is_won.is_(False),
                PipelineStage.is_lost.is_(False),
            )
            .order_by(PipelineStage.display_order.asc())
        )
    ).all()

    # Per-stage lead counts within the range. Group by the stage's
    # stable key (the column leads actually store) so the dict lookup
    # below is a direct hit.
    lead_stmt = (
        select(Lead.pipeline_stage, func.count(Lead.id))
        .where(
            Lead.org_id == org_id,
            Lead.created_at >= start,
            Lead.status == LeadStatus.active,
        )
        .group_by(Lead.pipeline_stage)
    )
    if not is_org_scope:
        lead_stmt = lead_stmt.where(Lead.assigned_to_id == caller_uuid)
    count_by_key: dict[str, int] = {
        key: int(count) for key, count in (await session.execute(lead_stmt)).all()
    }

    stages: list[FunnelStageBucket] = [
        FunnelStageBucket(
            stage_id=row.id,
            stage_name=row.name,
            stage_order=row.display_order,
            count=count_by_key.get(row.key, 0),
        )
        for row in stage_rows
    ]

    # Won/lost outcomes in the same range. Single statement, grouped
    # by status, so terminal counts come back together.
    outcome_stmt = (
        select(Lead.status, func.count(Lead.id))
        .where(
            Lead.org_id == org_id,
            Lead.created_at >= start,
            Lead.status.in_((LeadStatus.won, LeadStatus.lost)),
        )
        .group_by(Lead.status)
    )
    if not is_org_scope:
        outcome_stmt = outcome_stmt.where(Lead.assigned_to_id == caller_uuid)
    outcome_counts: dict[LeadStatus, int] = {
        s: int(c) for s, c in (await session.execute(outcome_stmt)).all()
    }
    won_count = outcome_counts.get(LeadStatus.won, 0)
    lost_count = outcome_counts.get(LeadStatus.lost, 0)

    total = sum(s.count for s in stages) + won_count + lost_count

    return DashboardFunnelResponse(
        range=range_str,
        scope=scope,
        total_leads_in_range=total,
        stages=stages,
        won_count=won_count,
        lost_count=lost_count,
    )


# --- Follow-ups widget --------------------------------------------------
#
# Same scope rule as `get_summary` — callers with `users.read` see the
# whole org, everyone else sees only tasks assigned to themselves. The
# widget's KPI card counts, chip counters, and list body are all derived
# from the same shared filter set so the numbers agree 1:1.


async def get_followups(
    session: AsyncSession,
    caller: User,
    *,
    bucket: FollowupBucket = "today",
    assigned_to: uuid.UUID | None = None,
    followup_type: str | None = None,
    priority: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> FollowupsResponse:
    """Assemble the follow-ups payload for the widget: scope resolution,
    5 KPI counts, and the paginated bucket-filtered list of Task rows.

    The ``assigned_to`` query param is only honoured for org-scope
    callers (``users.read``). Personal-scope callers are pinned to
    their own ``legacy_uuid`` regardless — no URL-hack peek at a
    peer's follow-ups.
    """
    org_id = caller.org_id
    if org_id is None:
        # Same defensive shape as get_summary — auth'd user with no
        # membership is an upstream bug; return an empty but
        # well-formed payload rather than 500.
        empty_counts = await _da.count_followups_by_bucket(
            session,
            org_id=uuid.UUID(int=0),
            today=datetime.now(UTC).date(),
            assignee_uuid=None,
        )
        return FollowupsResponse(
            scope="personal",
            bucket=bucket,
            counts=empty_counts,
            page=page,
            page_size=page_size,
            total=0,
            items=[],
        )

    today = datetime.now(UTC).date()
    is_org_scope = await _has_users_read(session, caller.role_id)

    if is_org_scope:
        assignee_uuid = assigned_to  # may be None (all-in-org)
        scope: Literal["org", "personal"] = "org"
    else:
        assignee_uuid = caller.legacy_uuid
        scope = "personal"

    counts = await _da.count_followups_by_bucket(
        session,
        org_id=org_id,
        today=today,
        assignee_uuid=assignee_uuid,
        followup_type=followup_type,
        priority=priority,
        q=q,
    )
    rows, total = await _da.list_tasks_for_bucket(
        session,
        org_id=org_id,
        bucket=bucket,
        today=today,
        assignee_uuid=assignee_uuid,
        followup_type=followup_type,
        priority=priority,
        q=q,
        page=page,
        page_size=page_size,
    )

    items = [_row_to_followup_item(r) for r in rows]
    return FollowupsResponse(
        scope=scope,
        bucket=bucket,
        counts=counts,
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )


def _row_to_followup_item(row: dict) -> FollowupItem:
    """Turn a DAL row-dict into the widget's FollowupItem shape. Handles
    the polymorphic linked-entity flattening + the notes-preview
    ellipsis."""
    entity_type = row.get("entity_type")
    entity_id = row.get("entity_id")
    entity_label = row.get("entity_label")
    linked: FollowupLinkedEntity | None = None
    if entity_type and entity_id:
        linked = FollowupLinkedEntity(
            type=entity_type,
            id=entity_id,
            label=entity_label or "(no name)",
        )

    notes_preview = row.get("notes_preview")
    # The SQL takes the first 100 chars via LEFT(); append an ellipsis
    # when the source description was longer so the operator sees the
    # truncation intent. We can't tell length inside SQL cheaply so we
    # append conditionally on the trimmed length hitting 100.
    if notes_preview and len(notes_preview) == 100:
        notes_preview = notes_preview + "…"

    return FollowupItem(
        id=row["id"],
        title=row["title"],
        due_at=row["due_at"],
        priority=row["priority"],
        status=row["status"],
        followup_type=row.get("followup_type"),
        notes_preview=notes_preview,
        assigned_to=FollowupAssignedTo(
            id=row["assigned_to_id"],
            name=row["assignee_name"],
        ),
        linked_entity=linked,
    )
