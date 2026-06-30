"""Staff module models.

Two tables:

- `StaffProfile` — one row per user that extends the auth `users` row
  with sales-specific fields (commission, monthly target, rating,
  employment status). `user_id` IS the primary key, so a user has at
  most one staff profile per org.
- `Attendance` — per-clock-in row. `hours` is a STORED generated
  column computed from `clock_out_at - clock_in_at`, NULL while the
  session is still open. The service enforces "at most one open
  session per user" via a query check, not a partial unique index,
  so the constraint stays in code where the 409 error message lives.

Both tenant-scoped, RLS-on, with org_id FK on every row per rule 2.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Computed,
    Date,
    DateTime,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmploymentStatus(str, enum.Enum):
    active = "active"
    leave = "leave"
    terminated = "terminated"


employment_status_enum = ENUM(
    EmploymentStatus,
    name="employment_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class StaffProfile(Base, TenantScoped):
    __tablename__ = "tbl_staff_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    monthly_target: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False, server_default=text("0"))
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        employment_status_enum,
        nullable=False,
        server_default=text("'active'"),
    )
    joined_at: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
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


class Attendance(Base, TenantScoped):
    __tablename__ = "tbl_attendance"
    __table_args__ = (Index("ix_attendance_user_date", "user_id", "date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # STORED generated column — minutes converted to hours. NULL until
    # the session is closed. The Postgres planner can read it without
    # recomputation on list / aggregate queries.
    hours: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        Computed(
            "EXTRACT(EPOCH FROM (clock_out_at - clock_in_at)) / 3600",
            persisted=True,
        ),
        nullable=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
