"""ORM mixins shared by all FurnitureCRM tenant-scoped models.

`TenantScoped`: declares the `org_id` foreign key column. Every entity that
belongs to a tenant inherits this mixin. Postgres Row-Level Security policies
(applied per migration in later steps) enforce the actual isolation; this
mixin provides the column they reference.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TenantScoped:
    """Mixin: every tenant-scoped table needs `org_id` FK to organizations."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
