"""Offset-pagination helper shared across list endpoints.

Every list service used to inline the same three calls:

    count_stmt = select(func.count()).select_from(...).where(...)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(base.offset((page - 1) * size).limit(size))).scalars().all()
    return list(rows), int(total)

:func:`paginate` consolidates that into one call. The count is derived
from the data ``stmt`` via ``stmt.order_by(None).subquery()`` so every
WHERE / JOIN the caller already applied is preserved — ORDER BY is
dropped because it's irrelevant for COUNT and would just waste work.

Pagination params are clamped defensively (``page >= 1``,
``1 <= size <= 200``) even though routers typically validate them via
FastAPI ``Query`` — so internal callers that pass through arbitrary
values can't accidentally request page 0 or a 100k-row payload.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_SIZE = 200


async def paginate(
    session: AsyncSession,
    stmt: Select,
    *,
    page: int,
    size: int,
) -> tuple[list[Any], int]:
    """Run ``stmt`` paginated; return ``(rows, total)``.

    `rows` is the list slice for the requested page; `total` is the
    full unscoped-by-page row count for the same WHERE clauses.
    """
    page = max(1, page)
    size = max(1, min(size, _MAX_SIZE))

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    rows = (await session.execute(stmt.offset((page - 1) * size).limit(size))).scalars().all()
    return list(rows), int(total)
