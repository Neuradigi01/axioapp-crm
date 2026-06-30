"""Pydantic v2 schemas for the staff module.

`StaffListItem` is the joined user + profile shape `GET /staff`
returns. Profile fields are `None` when the user has no
`staff_profiles` row yet (admin creates one via `PUT /staff/{id}`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.app.core.staff.models import EmploymentStatus
from src.app.shared.schemas import TimestampedOrgScopedOut


class StaffProfileUpsert(BaseModel):
    """Single payload for create-or-update — `PUT /staff/{id}` semantics."""

    commission_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    monthly_target: Decimal = Field(default=Decimal("0"), ge=0)
    rating: Decimal = Field(default=Decimal("0"), ge=0, le=5)
    employment_status: EmploymentStatus = EmploymentStatus.active
    joined_at: date | None = None


class StaffProfileOut(TimestampedOrgScopedOut):
    user_id: uuid.UUID
    commission_rate: Decimal
    monthly_target: Decimal
    rating: Decimal
    employment_status: EmploymentStatus
    joined_at: date


class StaffListItem(BaseModel):
    """Joined `users` + `staff_profiles` row. Profile fields are optional."""

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role_id: uuid.UUID
    is_active: bool

    # Profile fields — None when the user has no staff_profiles row yet.
    commission_rate: Decimal | None = None
    monthly_target: Decimal | None = None
    rating: Decimal | None = None
    employment_status: EmploymentStatus | None = None
    joined_at: date | None = None


class AttendanceOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    user_id: uuid.UUID
    clock_in_at: datetime
    clock_out_at: datetime | None
    hours: Decimal | None
    date: date
    notes: str | None


class ClockInPayload(BaseModel):
    notes: str | None = None


class ClockOutPayload(BaseModel):
    notes: str | None = None


class PerformanceOut(BaseModel):
    """Composed metrics for a staff member.

    `sales` and `target_progress` are placeholders (sales=0) until the
    invoices module ships. `leads_converted` is the count of leads
    assigned to this user with status='won'.
    """

    user_id: uuid.UUID
    leads_converted: int = Field(ge=0)
    leads_active: int = Field(ge=0)
    sales: Decimal = Field(default=Decimal("0"))
    monthly_target: Decimal = Field(default=Decimal("0"))
    target_progress_pct: float | None = None
    rating: Decimal = Field(default=Decimal("0"))
    commission_rate: Decimal = Field(default=Decimal("0"))
