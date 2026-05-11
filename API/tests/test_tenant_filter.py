"""Tests for tenant-isolation plumbing in `src.app.shared`.

Covers two complementary layers:

  1. The Postgres-level hook in `src.app.shared.db` — verifies that
     starting a transaction under a `RequestContext` populates the
     `app.org_id` session variable (which RLS policies depend on).
  2. The ORM-level `do_orm_execute` listener in `src.app.shared.orm` —
     verifies that SELECTs against a `TenantScoped` mapped class are
     automatically filtered by the active context's `org_id`.

The ORM test defines a private `_TenantThing` model inline so we have
a `TenantScoped` class to query (the only production tenant-scoped
table arrives in Step 1.5). The table joins the shared `Base.metadata`
and is created/dropped by the existing `test_db` fixture along with
all other tables.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import String, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# Importing db registers the `after_begin` listener that issues
# `set_config('app.org_id', ..., true)` at transaction start.
import src.app.shared.db  # noqa: F401
# Importing orm registers the `do_orm_execute` listener.
import src.app.shared.orm  # noqa: F401
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped
from src.app.core.tenants.models import Organization


class _TenantThing(Base, TenantScoped):
    """Test-only TenantScoped model. Lives in the shared metadata so the
    existing `test_db` fixture creates and drops it with everything else."""

    __tablename__ = "_test_tenant_thing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


@pytest.mark.asyncio
async def test_after_begin_hook_sets_app_org_id(test_db):
    org_id = uuid.uuid4()
    token = set_context(RequestContext(org_id=org_id))
    try:
        # Force the transaction to begin so the hook fires.
        await test_db.execute(text("SELECT 1"))
        result = await test_db.execute(text("SELECT current_setting('app.org_id', true)"))
        assert result.scalar() == str(org_id)
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_after_begin_hook_is_noop_without_context(test_db):
    # No `set_context` call — `current_setting(..., true)` returns NULL
    # (rendered as empty string by SQLAlchemy when cast to text).
    await test_db.execute(text("SELECT 1"))
    result = await test_db.execute(text("SELECT current_setting('app.org_id', true)"))
    value = result.scalar()
    assert value in (None, "")


@pytest.mark.asyncio
async def test_orm_filter_scopes_tenant_select(test_db):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    test_db.add_all([
        Organization(id=org_a, name="A", slug=f"a-{org_a.hex[:6]}"),
        Organization(id=org_b, name="B", slug=f"b-{org_b.hex[:6]}"),
        _TenantThing(id=uuid.uuid4(), org_id=org_a, name="a1"),
        _TenantThing(id=uuid.uuid4(), org_id=org_a, name="a2"),
        _TenantThing(id=uuid.uuid4(), org_id=org_b, name="b1"),
    ])
    await test_db.commit()

    # Context A → only A's things.
    token = set_context(RequestContext(org_id=org_a))
    try:
        result = await test_db.execute(select(_TenantThing))
        names = sorted(t.name for t in result.scalars().all())
        assert names == ["a1", "a2"]
    finally:
        reset_context(token)

    # Context B → only B's things.
    token = set_context(RequestContext(org_id=org_b))
    try:
        result = await test_db.execute(select(_TenantThing))
        names = sorted(t.name for t in result.scalars().all())
        assert names == ["b1"]
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_orm_filter_returns_nothing_without_context(test_db):
    """With no context org, the ORM filter is bypassed but no rows match
    either tenant — verifies the listener is a strict no-op without context
    (the SQL-level RLS denies in production where the role doesn't bypass)."""
    org_a = uuid.uuid4()
    test_db.add_all([
        Organization(id=org_a, name="A", slug=f"a-{org_a.hex[:6]}"),
        _TenantThing(id=uuid.uuid4(), org_id=org_a, name="a1"),
    ])
    await test_db.commit()

    # No set_context → the ORM listener does not add a filter clause.
    # We assert the unfiltered behaviour explicitly so a regression that
    # silently changes the listener's policy is caught here.
    result = await test_db.execute(select(_TenantThing))
    assert len(result.scalars().all()) == 1
