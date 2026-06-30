"""Models scoped to dev-only routes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base


class DemoCredential(Base):
    """One row per `is_demo=True` user, carrying its plaintext password.

    Read-only at the API layer (no insert / update / delete endpoints).
    Populated only by the seed scripts. Lives outside the tenant scope:
    the row IS the secret, identified solely by the user it pairs with.
    """

    __tablename__ = "tbl_demo_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    plain_password: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
