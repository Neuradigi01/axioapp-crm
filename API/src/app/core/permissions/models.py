"""Roles, permissions, and the join.

Layered model:
  - `Role` is tenant-scoped (each org defines its own roles).
  - `Permission` is GLOBAL — the registry of capability keys (e.g.
    `users.read`) is shared across tenants. Step 1.8 will let modules
    register their permission keys at startup; the rows live here.
  - `RolePermission` is the M:N link (also global, since role.id is
    unique and permission.id is unique).

`Role` therefore inherits `TenantScoped` (auto `org_id` column + ORM
filter + RLS policy via the 0003 migration). `Permission` and
`RolePermission` do not — they are not filtered by request context.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class Role(Base, TenantScoped):
    __tablename__ = "tbl_roles"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_roles_org_id_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Permission(Base):
    __tablename__ = "tbl_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    module: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RolePermission(Base):
    __tablename__ = "tbl_role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
