"""User model — backed by `tbl_user_login` (DR.6.3+).

`tbl_user_login` is the single source of truth for FurnitureCRM logins
after DR.6. It existed pre-DR.6 with a bigint PK and held one legacy
admin row (USR29684795) that drives `/accounts/admin-login` via the
separate `src.models.user.UserLogin` mapping. DR.6.1 added the
FurnitureCRM columns (email / org_id / role_id / full_name / phone /
is_demo / legacy_uuid / created_at / updated_at) and DR.6.2 migrated
the `users`-table rows in, preserving each user's original UUID
identity in the `legacy_uuid` bridge column.

Coexistence with the legacy `UserLogin` mapping
-----------------------------------------------
Both `src.models.user.UserLogin` (legacy template) and this `User`
class map the SAME `tbl_user_login` Table on the SAME shared
`MetaData`. The legacy class is loaded first via the side-effect
imports inside `src.app.shared.db`. We use
`__table_args__ = {"extend_existing": True}` so the layered class
extends the existing Table, and `__mapper_args__["exclude_properties"]`
to keep this mapper's namespace from being polluted by the legacy
2FA / `user_id` / `password_change_*` columns the FurnitureCRM auth
path doesn't read.

Identity
--------
`User.id` is the **bigint** storage PK — the same Python type and
column as `UserLogin.id`. The UUID identity that other tables'
`user_id` FKs and the JWT `sub` reference lives in `User.legacy_uuid`.
Callers writing UUID-typed FKs (audit_logs.user_id, AuthSession.user_id,
JWT sub) MUST use `user.legacy_uuid`, not `user.id`. This is exactly
the Risk #1 / Risk #2 the DR.6 plan tracks; DR.6.4 / DR.6.5 update
the audit / JWT / token call sites accordingly.

The legacy USR29684795 row has NULL email / org_id / role_id /
legacy_uuid, so it never matches any FurnitureCRM auth query (which
always filters by `email IS NOT NULL` and a specific `org_id`).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


# Placeholder `users` Table in MetaData. The `User` model below maps
# `tbl_user_login` (DR.6.3+), so the legacy `users` Table is no longer
# registered via a declarative class. But other models still declare
# `ForeignKey("users.id")` (auth_sessions.user_id, audit_logs.user_id)
# and SQLAlchemy resolves those FKs against MetaData by table name.
# This shim keeps the Table registered so those FK refs continue to
# resolve. The physical `users` table is preserved as a 2-week soak
# per the DR.6 plan; we'll retarget those FKs and drop this shim once
# the soak completes.
Table(
    "users",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    extend_existing=True,
)


class User(Base, TenantScoped):
    __tablename__ = "tbl_user_login"
    __table_args__ = {"extend_existing": True}
    # Existing Table columns are auto-mapped onto this class unless
    # excluded. The legacy 2FA + login-handle columns belong to the
    # legacy `UserLogin` mapping only; hide them from the layered
    # mapper so `user.user_id`, `user.two_factor_*` don't appear here.
    __mapper_args__ = {
        "exclude_properties": [
            "user_id",
            "two_factor_enabled",
            "two_factor_method",
            "two_factor_secret",
        ],
    }

    # `id` (bigint PK), `password`, and `is_active` are auto-mapped from
    # the existing Table columns declared on `UserLogin`. We don't
    # redeclare them here — `extend_existing` doesn't permit replacing
    # already-mapped columns.

    # FurnitureCRM columns (added in 0031). Nullable so the legacy
    # USR29684795 row coexists without a backfill.
    legacy_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    @property
    def password_hash(self) -> str:
        """Read-only alias for the legacy `password` column."""
        return self.password  # type: ignore[attr-defined]
