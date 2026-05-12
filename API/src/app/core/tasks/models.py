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
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class TaskStatus(str, enum.Enum):
    open = "open"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(str, enum.Enum):
    low = "low"
    med = "med"
    high = "high"


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


class Task(Base, TenantScoped):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_to_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    related_entity_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    related_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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
