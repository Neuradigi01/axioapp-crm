"""Generic async repository for FurnitureCRM models.

A thin layer over `AsyncSession` that exposes the standard CRUD shape
(`get`, `list`, `create`, `update`, `delete`) so services don't repeat
the same select/flush patterns.

Tenant isolation is *not* enforced here — it is enforced by:

  1. The `do_orm_execute` listener in `src.app.shared.orm`, which
     automatically adds `WHERE org_id = :ctx_org_id` to any Select
     against a `TenantScoped` model when a request context is set.
  2. Postgres Row-Level Security policies (added by `apply_rls(...)`
     in each tenant-scoped table's migration) backed by the
     `app.org_id` session variable set in `src.app.shared.db`.

That means callers can use this repository with a plain model class and
the right rows surface based on the active `RequestContext`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.db import Base


class Repository[T: Base]:
    """Generic CRUD for a single mapped class."""

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def get(self, id: uuid.UUID) -> T | None:
        result = await self.session.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[T]:
        result = await self.session.execute(select(self.model).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> T:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: T, **kwargs: Any) -> T:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: T) -> None:
        await self.session.delete(instance)
        await self.session.flush()
