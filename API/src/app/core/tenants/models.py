"""Organization (tenant) model — the multi-tenant root.

Every other FurnitureCRM table will reference `organizations.id` via an
`org_id` foreign key. Postgres Row-Level Security (added in Step 1.4)
enforces tenant isolation at the database layer.

This model uses SQLAlchemy 2.x typed-Mapped style and registers on the
shared `Base` so Alembic autogenerate picks it up alongside legacy models.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    pack_id: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'furniture'"))
    pack_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'INR'"))
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("18.00"),
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'Asia/Kolkata'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
