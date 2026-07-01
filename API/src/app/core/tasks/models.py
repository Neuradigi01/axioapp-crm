"""`Task` model — to-do items assigned to a user, optionally about an entity.

A task is the core CRM unit of work: "call Asha tomorrow about the
sofa quote", "follow up on lead #123", "review pipeline metrics". It
has an owner (`assigned_to_id`), a due time, and an optional link to
any tenant-scoped entity (contact, lead, walk_in, …) so the same UI
component can render "tasks on this contact" and "my open tasks
globally" off the same table.

Tenant-scoped (RLS on, ORM filter applied). Indexed for two hot
queries:
- `(org_id, assigned_to_id, status, due_at)` — "my open tasks, by due date".
- `(org_id, related_entity_type, related_entity_id)` — "tasks on this contact".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class TaskStatus(str, enum.Enum):
    open = "open"
    done = "done"
    cancelled = "cancelled"
    # `missed` is a terminal state distinct from `cancelled`: it means
    # the rep tried to follow up but the customer never responded (or
    # the nightly grooming job auto-closed a >7-day-overdue open task).
    # Surfaced on the dashboard's Missed bucket for audit + reporting.
    missed = "missed"


class TaskPriority(str, enum.Enum):
    low = "low"
    med = "med"
    high = "high"


class TaskFollowupType(str, enum.Enum):
    """Type of customer-touch action the task represents. NULL on the
    column = generic to-do (e.g. "review pipeline"); a non-NULL value
    tells the dashboard widget which type badge to render."""

    call = "call"
    whatsapp = "whatsapp"
    email = "email"
    document = "document"
    meeting = "meeting"
    other = "other"


task_status_enum = ENUM(
    TaskStatus,
    name="task_status",
    values_callable=lambda obj: [m.value for m in obj],
)

task_priority_enum = ENUM(
    TaskPriority,
    name="task_priority",
    values_callable=lambda obj: [m.value for m in obj],
)

task_followup_type_enum = ENUM(
    TaskFollowupType,
    name="task_followup_type",
    values_callable=lambda obj: [m.value for m in obj],
)


class Task(Base, TenantScoped):
    __tablename__ = "tbl_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    related_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum,
        nullable=False,
        server_default=text("'open'"),
    )
    priority: Mapped[TaskPriority] = mapped_column(
        task_priority_enum,
        nullable=False,
        server_default=text("'med'"),
    )
    followup_type: Mapped[TaskFollowupType | None] = mapped_column(
        task_followup_type_enum,
        nullable=True,
    )
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook AND by the tasks-service write
    # paths (update_task) so even no-activity edits (title fixes,
    # priority shuffles) refresh recency. Mirrors contacts / leads /
    # walk-ins / appointments.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
