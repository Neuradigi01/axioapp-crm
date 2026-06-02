"""DB query helpers shared across `app.core` and `app.packs`.

Two complementary 404 helpers consolidate the boilerplate that every
service used to inline by hand:

- :func:`ensure_found` — check the result of an existing ``get_X()``
  fetch. Most service code already has a typed ``get_X()`` helper
  returning ``Optional[T]``; this lifts the "raise 404 if None" noise
  out of every caller.
- :func:`get_or_404` — for inline lookups where no dedicated ``get_X()``
  helper exists.

Tenant scoping is **not** a parameter on either helper. The global
``do_orm_execute`` listener in :mod:`src.app.shared.orm` auto-injects
``WHERE org_id = ctx.org_id`` for every SELECT against a
``TenantScoped`` model whenever a request context is set — so the
helpers compose with that filter transparently.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


def ensure_found(row: T | None, *, entity: str) -> T:
    """Return ``row`` if not None, else raise HTTP 404.

    The detail message format is ``f"{entity} not found"`` — bit-identical
    to the hand-rolled blocks this replaces, so the API contract stays
    unchanged.
    """
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity} not found",
        )
    return row


async def get_or_404(
    session: AsyncSession,
    model: type[T],
    pk: Any,
    *,
    entity: str,
) -> T:
    """Fetch ``model`` by primary-key ``id``; raise 404 if not found."""
    row = (
        await session.execute(select(model).where(model.id == pk))
    ).scalar_one_or_none()
    return ensure_found(row, entity=entity)
