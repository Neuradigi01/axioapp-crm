"""Service layer for tasks.

Three categories of operation:

1. CRUD against the tasks row (`create_task`, `get_task`, `update_task`,
   `delete_task`).
2. The per-entity panel reader (`list_tasks_for_entity`) used by the
   "Tasks" tab on contact/lead detail pages.
3. The "my tasks" reader (`list_my_tasks`) backing the header popover
   — filters by `assigned_to_id == current user` and orders by
   `due_at` (nulls last), which matches what the index supports.

Audit events fire from each write path so the timeline picks up
status changes for free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import case, func, nulls_first, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities
from src.app.core.activities.models import ActivityType
from src.app.core.tasks import data_access as _da
from src.app.core.tasks.models import Task, TaskPriority, TaskStatus
from src.app.core.tasks.schemas import TaskCreate, TaskUpdate
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found

_TASK_ENTITY = "task"

DueFilter = Literal["today", "overdue", "upcoming"]
SortBy = Literal["due_at", "priority", "title", "created_at", "last_activity_at"]
SortDir = Literal["asc", "desc"]


# Priority ordering when sorting by priority — Postgres compares the
# enum's storage values alphabetically ("high" < "low" < "med"), which
# isn't the human ordering. CASE-coerce to a numeric rank so high tasks
# surface first.
_PRIORITY_RANK = case(
    {
        TaskPriority.high: 1,
        TaskPriority.med: 2,
        TaskPriority.low: 3,
    },
    value=Task.priority,
)


def _apply_task_filters(
    stmt,
    *,
    status_filter: TaskStatus | None,
    priority: TaskPriority | None,
    q: str | None,
    due_filter: DueFilter | None,
    sort_by: SortBy,
    sort_dir: SortDir,
):
    """Compose the shared WHERE + ORDER clauses for `/tasks/me` and `/tasks/all`."""
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    if due_filter == "today":
        stmt = stmt.where(
            Task.due_at.is_not(None),
            func.date(Task.due_at) == func.current_date(),
        )
    elif due_filter == "overdue":
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at < func.now())
    elif due_filter == "upcoming":
        stmt = stmt.where(Task.due_at.is_not(None), Task.due_at > func.now())

    if sort_by == "priority":
        col = _PRIORITY_RANK
    elif sort_by == "title":
        col = Task.title
    elif sort_by == "created_at":
        col = Task.created_at
    elif sort_by == "last_activity_at":
        col = Task.last_activity_at
    else:
        col = Task.due_at

    ordered = col.asc() if sort_dir == "asc" else col.desc()
    if sort_by == "due_at":
        ordered = nulls_last(col.asc()) if sort_dir == "asc" else nulls_first(col.desc())
    elif sort_by == "last_activity_at":
        ordered = nulls_last(col.asc()) if sort_dir == "asc" else nulls_last(col.desc())

    return stmt.order_by(ordered, Task.created_at.desc())


_SNAPSHOT_FIELDS = (
    "id",
    "title",
    "description",
    "due_at",
    "assigned_to_id",
    "related_entity_type",
    "related_entity_id",
    "status",
    "priority",
    "followup_type",
    "custom_data",
)


def _snapshot(t: Task) -> dict[str, Any]:
    return snapshot(t, fields=_SNAPSHOT_FIELDS)


def _task_snapshot_for_event(t: Task) -> dict[str, Any]:
    """Rich event-payload snapshot. Kept separate from ``_snapshot`` (the
    audit snapshot) because the workflow trigger payload needs the ISO
    datetime + a couple of derived fields the audit trail doesn't care
    about. Any change here should be additive so subscribers built
    against the current shape keep working."""
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "priority": t.priority.value if hasattr(t.priority, "value") else str(t.priority),
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "assigned_to_id": str(t.assigned_to_id) if t.assigned_to_id else None,
        "related_entity_type": t.related_entity_type,
        "related_entity_id": (
            str(t.related_entity_id) if t.related_entity_id else None
        ),
        "followup_type": (
            t.followup_type.value
            if t.followup_type is not None and hasattr(t.followup_type, "value")
            else (str(t.followup_type) if t.followup_type is not None else None)
        ),
    }


async def _build_task_event_payload(
    session: AsyncSession, *, task: Task, org_id: uuid.UUID
) -> dict[str, Any]:
    """Assemble the trigger-event payload for a task.

    Snapshots the assignee (User), the linked contact (if the task
    points at one via `related_entity_type='contact'`), and the org
    alongside the task itself — so workflow subscribers can render
    variables like ``{{contact.full_name}}``, ``{{assignee.email}}``,
    ``{{task.title}}`` without any additional DB round-trips.
    """
    from sqlalchemy import select as _select

    from src.app.core.contacts.models import Contact
    from src.app.core.tenants.models import Organization
    from src.app.core.users.models import User

    payload: dict[str, Any] = {
        "task_id": str(task.id),
        "assigned_to_id": str(task.assigned_to_id) if task.assigned_to_id else None,
        "contact_id": (
            str(task.related_entity_id)
            if task.related_entity_type == "contact" and task.related_entity_id
            else None
        ),
        "task": _task_snapshot_for_event(task),
    }

    if task.assigned_to_id is not None:
        assignee = (
            await session.execute(_select(User).where(User.legacy_uuid == task.assigned_to_id))
        ).scalar_one_or_none()
        if assignee is not None:
            payload["assignee"] = {
                "id": str(assignee.legacy_uuid),
                "full_name": assignee.full_name,
                "email": assignee.email,
            }

    if task.related_entity_type == "contact" and task.related_entity_id:
        contact = (
            await session.execute(_select(Contact).where(Contact.id == task.related_entity_id))
        ).scalar_one_or_none()
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }

    org = (
        await session.execute(_select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is not None:
        payload["org"] = {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
        }

    return payload


def _fmt_due_at(dt: datetime | None) -> str:
    """Human-friendly due-at string for notification bodies. Localises
    to the org's TZ later if we want; UTC-naive is fine for the v1
    since the assignee already knows their own timezone context."""
    if dt is None:
        return "no due date"
    return dt.strftime("%b %d, %H:%M")


async def _notify_task_event(
    *,
    org_id: uuid.UUID,
    task: Task,
    event_type: str,
) -> None:
    """Send a bell + (opt-in) email notification to the task's assignee.

    Separate from the workflow-bus publisher — the publisher fires
    user-authored workflows (custom template, filters, etc.), while
    this call is the guaranteed built-in notification the assignee
    gets regardless of whether any workflow is configured.

    Safe to call after commit; every failure is swallowed by
    `notifications.notify` itself.
    """
    if task.assigned_to_id is None:
        return
    if event_type == "task.assigned":
        title = f"New task: {task.title}"
        body = f"Due {_fmt_due_at(task.due_at)} · Priority {task.priority.value}"
    elif event_type == "task.completed":
        title = f"Task completed: {task.title}"
        body = "Marked done."
    else:
        return

    payload: dict[str, Any] = {
        "task_id": str(task.id),
        "title": task.title,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "priority": task.priority.value,
        "assigned_to_id": str(task.assigned_to_id),
        "related_entity_type": task.related_entity_type,
        "related_entity_id": (
            str(task.related_entity_id) if task.related_entity_id else None
        ),
    }

    from src.app.core.notifications import service as notifications

    await notifications.notify(
        org_id=org_id,
        user_id=task.assigned_to_id,
        type=event_type,
        title=title,
        body=body,
        payload=payload,
    )


async def _publish_task_assigned(
    session: AsyncSession, *, org_id: uuid.UUID, task: Task
) -> None:
    """Publish `task.assigned` to the events bus. Fires on both the
    initial assignment (task creation with a non-creator assignee) and
    every subsequent reassignment. The `event_id` includes the current
    assignee so a reassign back-and-forth still delivers each hop —
    dedupe is per (task, assignee), not per task.

    Wrapped in a broad try so an event-bus outage never blocks the
    caller's mutation."""
    try:
        from src.app.core.events.bus import publish as events_publish

        payload = await _build_task_event_payload(session, task=task, org_id=org_id)
        await events_publish(
            "task.assigned",
            payload,
            org_id=org_id,
            event_id=f"task_assigned:{task.id}:{task.assigned_to_id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "tasks.publish_task_assigned failed org=%s task=%s",
            org_id,
            task.id,
        )


async def _publish_task_completed(
    session: AsyncSession, *, org_id: uuid.UUID, task: Task
) -> None:
    """Publish `task.completed` when a task's status transitions to
    ``done``. Idempotent per task — a duplicate publish is caught by
    the events bus dedupe on `event_id`."""
    try:
        from src.app.core.events.bus import publish as events_publish

        payload = await _build_task_event_payload(session, task=task, org_id=org_id)
        await events_publish(
            "task.completed",
            payload,
            org_id=org_id,
            event_id=f"task_completed:{task.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "tasks.publish_task_completed failed org=%s task=%s",
            org_id,
            task.id,
        )


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    """Return a single task, scoped to the active tenant."""
    return await _da.get_task_by_id(session, task_id)


async def create_task(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: TaskCreate,
) -> Task:
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_TASK_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
    )
    task = Task(
        org_id=org_id,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        assigned_to_id=payload.assigned_to_id or current_user_id,
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
        priority=payload.priority,
        followup_type=payload.followup_type,
        status=TaskStatus.open,
        custom_data=cleaned_custom,
    )
    _da.insert_task(session, task)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.created",
        entity_type="task",
        entity_id=task.id,
        after=_snapshot(task),
    )

    # Fire `task.assigned` only when the assignee isn't the creator —
    # a rep creating a self-note doesn't need an email to themselves.
    # Explicit assignees (delegation) always publish, even if the
    # picked user is the creator, because that was a conscious action.
    is_self_assign = (
        payload.assigned_to_id is None and task.assigned_to_id == current_user_id
    )
    if not is_self_assign:
        await _publish_task_assigned(session, org_id=org_id, task=task)
        await _notify_task_event(
            org_id=org_id, task=task, event_type="task.assigned"
        )
    return task


async def update_task(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    payload: TaskUpdate,
) -> Task:
    task = ensure_found(await get_task(session, task_id), entity="task")

    before = _snapshot(task)
    # Snapshot the specific fields that drive workflow events BEFORE
    # applying the patch, so we can compare to the post-write state.
    prior_assignee = task.assigned_to_id
    prior_status = task.status
    changes = payload.model_dump(exclude_unset=True)
    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_TASK_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )
    for key, value in changes.items():
        setattr(task, key, value)
    # Bump `last_activity_at` independently of the activity-insert
    # hook — not every task PATCH writes an activity (a title fix
    # doesn't, for instance), but the user still expects "recent
    # activity" to surface the edit.
    task.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.updated",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after=_snapshot(task),
    )

    # Detect the two transitions the workflow engine cares about and
    # publish independently — both can happen in the same PATCH (a
    # user might reassign + complete in one call), and each is a
    # separate trigger event.
    if task.assigned_to_id != prior_assignee and task.assigned_to_id is not None:
        await _publish_task_assigned(session, org_id=task.org_id, task=task)
        await _notify_task_event(
            org_id=task.org_id, task=task, event_type="task.assigned"
        )
    if task.status == TaskStatus.done and prior_status != TaskStatus.done:
        await _publish_task_completed(session, org_id=task.org_id, task=task)
        await _notify_task_event(
            org_id=task.org_id, task=task, event_type="task.completed"
        )
    return task


async def mark_task_missed(
    session: AsyncSession, *, task_id: uuid.UUID
) -> Task:
    """Flip a task from ``open`` → ``missed``.

    Terminal-status transitions are refused with 409 so a stale click
    on a follow-up already closed (either completed or previously
    marked missed) doesn't overwrite history. ``cancelled`` is also
    refused — a rep who cancelled a task shouldn't have it silently
    re-labelled as missed by a race.

    Emits ``tasks.marked_missed`` audit so the linked contact's
    timeline records why the follow-up stopped.
    """
    task = ensure_found(await get_task(session, task_id), entity="task")

    if task.status != TaskStatus.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Task is {task.status.value}; only open tasks can be marked missed."
            ),
        )

    before = _snapshot(task)
    task.status = TaskStatus.missed
    task.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(task)

    await log_entity_change(
        action="tasks.marked_missed",
        entity_type="task",
        entity_id=task.id,
        before=before,
        after=_snapshot(task),
    )
    return task


async def delete_task(session: AsyncSession, *, task_id: uuid.UUID) -> None:
    task = ensure_found(await get_task(session, task_id), entity="task")
    before = _snapshot(task)
    task_uuid = task.id
    await _da.delete_task_row(session, task)
    await session.commit()

    await log_entity_change(
        action="tasks.deleted",
        entity_type="task",
        entity_id=task_uuid,
        before=before,
    )


async def list_tasks_for_entity(
    session: AsyncSession,
    *,
    related_entity_type: str,
    related_entity_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Tasks attached to one entity, latest-due first (with overdue at top)."""
    return await _da.list_tasks_for_entity_query(
        session,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        status_filter=status_filter,
        page=page,
        size=size,
    )


async def list_my_tasks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    q: str | None = None,
    due_filter: DueFilter | None = None,
    sort_by: SortBy = "due_at",
    sort_dir: SortDir = "asc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Caller's tasks. Filters mirror `/tasks/all`."""
    base = select(Task).where(Task.assigned_to_id == user_id)
    base = _apply_task_filters(
        base,
        status_filter=status_filter,
        priority=priority,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return await _da.paginate_tasks_select(session, base, page=page, size=size)


async def list_all_in_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assigned_to_id: uuid.UUID | None = None,
    q: str | None = None,
    due_filter: DueFilter | None = None,
    sort_by: SortBy = "due_at",
    sort_dir: SortDir = "asc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[Task], int]:
    """Every task in the org — gated by `users.read` at the router layer."""
    base = select(Task).where(Task.org_id == org_id)
    if assigned_to_id is not None:
        base = base.where(Task.assigned_to_id == assigned_to_id)
    base = _apply_task_filters(
        base,
        status_filter=status_filter,
        priority=priority,
        q=q,
        due_filter=due_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return await _da.paginate_tasks_select(session, base, page=page, size=size)


# --- Bulk actions ----------------------------------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org."""
    if not await _da.user_has_active_membership(session, org_id=org_id, user_uuid=user_uuid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def bulk_reassign_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Bulk reassign. Tasks require an owner (the column is NOT NULL),
    so `None` is rejected with 422 even though the schema typing is
    optional. Rows already owned by the target are skipped (no-op,
    not an error).

    Batched hydrate (``list_tasks_by_ids_in_org``) replaces the prior
    per-id ``get_task`` loop, and every touched row now emits a
    ``tasks.reassigned`` audit entry to match the single-row path —
    bulk previously wrote timeline Activities but no audit trail."""
    if assigned_to_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tasks require an owner; assigned_to_id cannot be null",
        )
    await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    # One SELECT for the whole batch; the DAL enforces org_id.
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)

    # Collect per-row before/after snapshots so we can write audit
    # entries AFTER commit — a subscriber crash mid-loop then can't
    # roll back a whole reassign batch.
    reassigned = 0
    audit_batch: list[tuple[uuid.UUID, dict[str, Any], dict[str, Any]]] = []
    reassigned_tasks: list[Task] = []
    for task in tasks:
        if task.assigned_to_id == assigned_to_id:
            continue
        before_id = task.assigned_to_id
        before_snap = _snapshot(task)
        task.assigned_to_id = assigned_to_id
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type="task",
            entity_id=task.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
            user_id=actor_user_id,
        )
        audit_batch.append((task.id, before_snap, _snapshot(task)))
        reassigned_tasks.append(task)
        reassigned += 1

    await session.commit()

    for task_id, before_snap, after_snap in audit_batch:
        await log_entity_change(
            action="tasks.reassigned",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
            after=after_snap,
        )
    for task in reassigned_tasks:
        await _publish_task_assigned(session, org_id=org_id, task=task)
        await _notify_task_event(org_id=org_id, task=task, event_type="task.assigned")
    return reassigned


async def bulk_mark_done_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> tuple[int, int]:
    """Move every open (or cancelled) task in the batch to ``done``.

    Batched hydrate replaces the prior per-id ``get_task`` loop, and
    every flipped row now emits a ``tasks.marked_done`` audit entry —
    the single-row PATCH path calls ``tasks.updated`` with before/after
    snapshots; bulk was previously silent, so subscribers listening
    for task completion (e.g. workflow triggers) never saw bulk-done
    events."""
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)

    done = 0
    skipped = 0
    audit_batch: list[tuple[uuid.UUID, dict[str, Any], dict[str, Any]]] = []
    completed_tasks: list[Task] = []
    for task in tasks:
        if task.status == TaskStatus.done:
            skipped += 1
            continue
        before_snap = _snapshot(task)
        task.status = TaskStatus.done
        task.last_activity_at = datetime.now(UTC)
        audit_batch.append((task.id, before_snap, _snapshot(task)))
        completed_tasks.append(task)
        done += 1

    await session.commit()

    for task_id, before_snap, after_snap in audit_batch:
        await log_entity_change(
            action="tasks.marked_done",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
            after=after_snap,
        )
    for task in completed_tasks:
        await _publish_task_completed(session, org_id=org_id, task=task)
        await _notify_task_event(org_id=org_id, task=task, event_type="task.completed")
    return done, skipped


async def bulk_delete_tasks(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard delete in bulk. Single DELETE statement scoped by org_id
    so a misconfigured tenant context can't leak cross-org rows.

    Snapshots each row *before* the DELETE so we can write one
    ``tasks.deleted`` audit entry per gone row (matches the single-row
    ``delete_task`` path — the bulk path used to be silent, so any
    operator or subscriber replaying the audit trail would see rows
    vanish with no explanation).

    Tasks have no outbound FK RESTRICT dependents at the DB level so
    there is nothing to catch — leads.bulk_delete needs the
    IntegrityError wrap; tasks does not."""
    tasks = await _da.list_tasks_by_ids_in_org(session, ids=ids, org_id=org_id)
    snapshots = [(t.id, _snapshot(t)) for t in tasks]

    rowcount = await _da.bulk_delete_tasks_by_ids(session, ids=ids, org_id=org_id)
    await session.commit()

    for task_id, before_snap in snapshots:
        await log_entity_change(
            action="tasks.deleted",
            entity_type=_TASK_ENTITY,
            entity_id=task_id,
            before=before_snap,
        )
    return rowcount


# Re-export enums so callers get a stable import path through this module.
__all__ = [
    "DueFilter",
    "SortBy",
    "SortDir",
    "TaskPriority",
    "TaskStatus",
    "bulk_delete_tasks",
    "bulk_mark_done_tasks",
    "bulk_reassign_tasks",
    "create_task",
    "delete_task",
    "get_task",
    "list_all_in_org",
    "list_my_tasks",
    "list_tasks_for_entity",
    "update_task",
]
