"""Organization (tenant) model — the multi-tenant root.

Every other FurnitureCRM table will reference `organizations.id` via an
`org_id` foreign key. Postgres Row-Level Security (added in Step 1.4)
enforces tenant isolation at the database layer.

This model uses SQLAlchemy 2.x typed-Mapped style and registers on the
shared `Base` so Alembic autogenerate picks it up alongside legacy models.
"""

import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, Time, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base


class Organization(Base):
    __tablename__ = "tbl_organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # CRM template the org chose at onboarding ("base", "furniture",
    # "real_estate", ...). The literal "pending" is a sentinel meaning
    # "register completed, onboarding not yet finalized" — see the
    # onboarding-setup track.
    template_id: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    template_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'INR'"))
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("18.00"),
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Kolkata'")
    )
    created_via: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'normal_signup'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # tasks/automation-engine Step 13 — send-time compliance controls.
    # The marketing-send guard checks these before dispatching any
    # marketing-category automation run:
    #   * Quiet hours: marketing sends in the window
    #     ``[quiet_hours_start, quiet_hours_end)`` (in
    #     ``quiet_hours_timezone``) are deferred to ``quiet_hours_end``
    #     of the same or next day. The default 21:00–09:00 IST matches
    #     the DPDP guidance + standard "don't message after dinner"
    #     courtesy window operators expect.
    #   * Frequency cap: when ``marketing_frequency_cap_enabled`` is
    #     true, no contact receives more than
    #     ``marketing_frequency_cap_per_week`` marketing sends in any
    #     rolling 7-day window. Cap = 0 means "no marketing sends".
    # Transactional + service templates bypass all three checks; only
    # ``TemplateCategory.marketing`` runs hit the guard.
    quiet_hours_start: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        server_default=text("'21:00:00'"),
    )
    quiet_hours_end: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        server_default=text("'09:00:00'"),
    )
    quiet_hours_timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'Asia/Kolkata'"),
    )
    marketing_frequency_cap_per_week: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("3"),
    )
    marketing_frequency_cap_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
