"""Unit tests for `paginate(session, stmt, *, page, size)`.

The session is mocked so no live DB is needed. We assert:

1. The helper calls `session.execute` twice — once with the count
   statement (derived from `stmt.order_by(None).subquery()`), once
   with the data statement (`stmt.offset(...).limit(...)`).
2. It returns `(rows, total)` where `rows` is the data result's
   `.scalars().all()` projection and `total` is the count result's
   `.scalar_one()`.
3. `page` and `size` are clamped: `page >= 1`, `1 <= size <= 200`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.app.shared.db.pagination import paginate


class _Base(DeclarativeBase):
    pass


class _Row(_Base):
    __tablename__ = "_test_paginate_rows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)


def _mock_session(*, rows: list[object], total: int) -> MagicMock:
    """Mock session whose first `execute(...)` returns the count and
    second returns the data slice."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    data_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    data_result.scalars.return_value = scalars

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[count_result, data_result])
    return session


async def test_returns_rows_and_total() -> None:
    rows = [_Row(id=1, name="a"), _Row(id=2, name="b")]
    session = _mock_session(rows=rows, total=42)
    result_rows, total = await paginate(
        session, select(_Row), page=1, size=10
    )
    assert result_rows == rows
    assert total == 42
    assert session.execute.await_count == 2


async def test_empty_page_returns_empty_list_and_zero_total() -> None:
    session = _mock_session(rows=[], total=0)
    rows, total = await paginate(session, select(_Row), page=1, size=50)
    assert rows == []
    assert total == 0


async def test_offset_and_limit_match_page_and_size() -> None:
    """`page=3, size=25` should issue a data query with `OFFSET 50 LIMIT 25`."""
    session = _mock_session(rows=[], total=0)
    await paginate(session, select(_Row), page=3, size=25)

    # Second execute call is the data query — check its compiled SQL.
    data_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(data_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 25" in compiled
    assert "OFFSET 50" in compiled


async def test_page_lower_bound_is_clamped_to_one() -> None:
    """`page < 1` should be clamped to 1 (offset 0)."""
    session = _mock_session(rows=[], total=0)
    await paginate(session, select(_Row), page=0, size=50)

    data_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(data_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "OFFSET 0" in compiled


async def test_size_upper_bound_is_clamped_to_200() -> None:
    """`size > 200` should be clamped to 200 (rate-limit guard)."""
    session = _mock_session(rows=[], total=0)
    await paginate(session, select(_Row), page=1, size=10_000)

    data_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(data_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 200" in compiled


async def test_size_lower_bound_is_clamped_to_one() -> None:
    """`size < 1` should be clamped to 1."""
    session = _mock_session(rows=[], total=0)
    await paginate(session, select(_Row), page=1, size=0)

    data_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(data_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 1" in compiled


async def test_count_strips_order_by_from_subquery() -> None:
    """Counting on an ordered stmt should drop ORDER BY before subquerying —
    ORDER BY is irrelevant for COUNT and just wastes work."""
    session = _mock_session(rows=[], total=0)
    ordered = select(_Row).order_by(_Row.name.desc())
    await paginate(session, ordered, page=1, size=10)

    count_stmt = session.execute.await_args_list[0].args[0]
    compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY" not in compiled.upper()
