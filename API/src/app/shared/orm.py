"""ORM plumbing for tenant-scoped models.

`TenantScoped` is a mixin every tenant-owned model inherits. It declares
the `org_id` foreign-key column that Postgres Row-Level Security
policies reference.

The module-level `do_orm_execute` event listener auto-injects
`WHERE org_id = :ctx_org_id` into every ORM-level SELECT against a
`TenantScoped` mapped class when a request context is set. This belt
complements the Postgres-level RLS suspenders: it short-circuits queries
in environments where the connecting role might bypass RLS (e.g. dev
runs as the table owner) and keeps unscoped joins honest.

The listener uses `with_loader_criteria(..., include_aliases=True)` so
the predicate is applied wherever the class appears in a statement —
including joins and subqueries.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from src.app.shared.context import get_context


class TenantScoped:
    """Mixin: every tenant-scoped table needs `org_id` FK to organizations."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


@event.listens_for(Session, "do_orm_execute")
def _tenant_filter(orm_execute_state) -> None:
    """Auto-apply `WHERE org_id = :ctx_org_id` for SELECTs on TenantScoped models."""
    if not orm_execute_state.is_select:
        return

    ctx = get_context()
    if ctx.org_id is None:
        return

    org_id = ctx.org_id
    orm_execute_state.statement = orm_execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.org_id == org_id,
            include_aliases=True,
        )
    )
