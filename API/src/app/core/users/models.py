"""User model — three-table split (DR.7+).

After DR.7 the FurnitureCRM user is **three rows joined**:

  - `tbl_user_login` — auth (id, user_id text login-handle, password,
                       2FA, is_active). Mapped here as `User`.
  - `tbl_user_info`  — profile (first_name, last_name, email,
                       mobile_no, country/state, verification flags).
                       Mapped on the legacy `src.models.user.UserInfo`
                       class, re-exported here as `UserInfo`.
  - `tbl_organization_members` — N:M between login and organisations,
                       holds role_id, status, is_demo, is_active per
                       (user, org) pair. Mapped here as `OrganizationMember`.

`User.id` is the bigint storage PK of `tbl_user_login`. The UUID
identity that audit FKs, AuthSession.user_id, staff_sessions.user_id,
and the JWT `sub` reference lives in `User.legacy_uuid`. The
DR.6.2 data migration populated `legacy_uuid` from the original
`users.id` values; the soak-and-drop of the `users` table is tracked
in [tasks/phase-4.5-demo-roles-setup/README.md].

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

User.email / .full_name / .phone / .org_id / .role_id / .is_demo
----------------------------------------------------------------
Kept as Python `@property` aliases so callers using attribute access
(`user.email`, `user.org_id`, etc.) keep working without a sweep. They
delegate to the joined `info` / `active_membership` rows. For
SQLAlchemy SQL expressions, callers must JOIN through `UserInfo` and
`OrganizationMember` directly — properties are not query-expressible.

`User` is NOT `TenantScoped` — the org column lives on
`OrganizationMember`, not on `tbl_user_login`. Queries that need
tenant scoping must JOIN through `OrganizationMember` and filter on
`OrganizationMember.organization_id`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.shared.db import Base

# Re-export the legacy `tbl_user_info` mapping. We use the legacy
# class as-is (1:1 with tbl_user_login, FK on member_id) so the
# layered code can `from src.app.core.users.models import UserInfo`
# without setting up a duplicate mapper.
from src.models.user import UserInfo  # noqa: F401

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


class User(Base):
    __tablename__ = "tbl_user_login"
    __table_args__ = {"extend_existing": True}
    __mapper_args__ = {
        # Hide legacy `UserLogin`-only columns from this mapper:
        # the 2FA tuple plus the TEXT login-handle. The DR.6.1
        # FurnitureCRM columns are also excluded here — `email`,
        # `full_name`, `phone`, `role_id`, `is_demo`, `created_at`,
        # `updated_at`, `org_id` — because after DR.7 they live on
        # `tbl_user_info` and `tbl_organization_members`. They are
        # exposed back via @property aliases below for read-only
        # attribute access. The `org_id` exclusion also keeps the
        # `do_orm_execute` tenant-filter listener from injecting a
        # stale `WHERE org_id = ?` clause once the column is dropped
        # by migration 0035.
        "exclude_properties": [
            "user_id",
            "two_factor_enabled",
            "two_factor_method",
            "two_factor_secret",
            "email",
            "full_name",
            "phone",
            "role_id",
            "is_demo",
            "created_at",
            "updated_at",
            "org_id",
        ],
    }

    # `id` (bigint PK), `password`, and `is_active` are auto-mapped from
    # the existing Table columns declared on `UserLogin`. We don't
    # redeclare them here — `extend_existing` doesn't permit replacing
    # already-mapped columns.

    # The one DR.6.1 column we keep on `tbl_user_login`: the UUID
    # identity bridge. Every cross-table `user_id` FK in the codebase
    # (audit_logs, auth_sessions, staff_sessions, staff_profiles,
    # demo_credentials, JWT sub) is a UUID, and `legacy_uuid` is what
    # those FKs ultimately resolve against until a future migration
    # retargets them to `tbl_user_login.id` (bigint).
    legacy_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationships introduced in DR.7.3 — the three-table split.
    # `info` is the profile row on `tbl_user_info` (one per user).
    # `memberships` is the list of (org, role) rows on
    # `tbl_organization_members`. Use `selectin` loading so a single
    # `select(User)` always pulls the joined profile + memberships in
    # one extra query — avoids N+1 on /me and similar.
    info: Mapped[UserInfo | None] = relationship(
        "UserInfo",
        primaryjoin="User.id == UserInfo.member_id",
        foreign_keys="UserInfo.member_id",
        uselist=False,
        viewonly=True,
        lazy="selectin",
    )
    memberships: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember",
        primaryjoin="User.id == OrganizationMember.user_member_id",
        foreign_keys="OrganizationMember.user_member_id",
        viewonly=True,
        lazy="selectin",
    )

    @property
    def active_membership(self) -> OrganizationMember | None:
        """The user's currently-active org membership.

        Enforced at the DB level by the partial unique index
        `uq_org_members_one_active_per_user` (one active row per
        `user_member_id`). For a request to see this user via the
        auth path, exactly one row of `memberships` should have
        `is_active=true`.
        """
        for m in self.memberships:
            if m.is_active:
                return m
        return None

    @property
    def password_hash(self) -> str:
        """Read-only alias for the legacy `password` column."""
        return self.password  # type: ignore[attr-defined]

    # --- DR.6.1 column shims --------------------------------------------
    # These attributes used to live on `tbl_user_login` (added DR.6.1,
    # dropped DR.7.5). They're now read off the joined `info` and
    # `active_membership` rows. Property-only — not query-expressible.

    @property
    def email(self) -> str | None:
        return self.info.email if self.info else None

    @property
    def full_name(self) -> str:
        if self.info is None:
            return ""
        parts = [self.info.first_name, self.info.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def phone(self) -> str | None:
        return self.info.mobile_no if self.info else None

    @property
    def org_id(self) -> uuid.UUID | None:
        m = self.active_membership
        return m.organization_id if m else None

    @property
    def role_id(self) -> uuid.UUID | None:
        m = self.active_membership
        return m.role_id if m else None

    @property
    def is_demo(self) -> bool:
        m = self.active_membership
        return m.is_demo if m else False

    @property
    def created_at(self) -> datetime | None:
        m = self.active_membership
        return m.joined_at if m else None

    @property
    def updated_at(self) -> datetime | None:
        # No per-user updated_at after DR.7 — we don't track when an
        # org membership was last touched. Surface `joined_at` so
        # serializers that include `updated_at` don't break.
        m = self.active_membership
        return m.joined_at if m else None


class OrganizationMember(Base):
    """Per-(org, user) membership row, with role + per-membership state.

    Introduced in DR.7.1 to lift org + role + is_demo + status off
    `tbl_user_login`. One row per active (org, user) pair; the partial
    unique index `uq_org_members_one_active_per_user` constrains a
    user to a single *active* membership across all orgs at a time,
    while leaving historical/paused memberships in place.

    Not `TenantScoped` — the tenant column is `organization_id`
    (matching the reference architecture), not `org_id`, so the
    `do_orm_execute` auto-filter listener doesn't apply. Callers that
    query `OrganizationMember` directly must filter by
    `organization_id` explicitly.
    """

    __tablename__ = "tbl_organization_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_member_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tbl_user_login.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ui_preferences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
