"""Unit tests for `ensure_found` and `get_or_404`.

Both helpers are tested without a live DB: ``ensure_found`` is pure
Python, and ``get_or_404`` runs against a real (but tiny) declarative
mapped class with the session mocked so no SQL is actually issued.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.app.shared.db.queries import ensure_found, get_or_404


# --- ensure_found ---------------------------------------------------------


def test_ensure_found_returns_row_when_present() -> None:
    obj = {"id": 1, "name": "a"}
    assert ensure_found(obj, entity="thing") is obj


def test_ensure_found_raises_404_when_none() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_found(None, entity="thing")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "thing not found"


def test_ensure_found_passes_entity_into_detail() -> None:
    """Detail format is f'{entity} not found' — bit-identical to the
    hand-rolled blocks this replaces."""
    for entity, expected in [
        ("contact", "contact not found"),
        ("walk-in", "walk-in not found"),
        ("scoring rule", "scoring rule not found"),
        ("catalog_item_id", "catalog_item_id not found"),
    ]:
        with pytest.raises(HTTPException) as exc_info:
            ensure_found(None, entity=entity)
        assert exc_info.value.detail == expected


# --- get_or_404 -----------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Widget(_Base):
    """Real mapped class so `select(_Widget).where(_Widget.id == pk)`
    compiles; the session is mocked so no SQL is issued."""

    __tablename__ = "_test_widgets_for_get_or_404"
    id: Mapped[str] = mapped_column(String, primary_key=True)


def _mock_session(found: object | None) -> MagicMock:
    """Return a mock AsyncSession whose `execute(...)` resolves to a
    result whose `.scalar_one_or_none()` returns `found`."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = found
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def test_get_or_404_returns_row_when_present() -> None:
    row = _Widget(id="w1")
    session = _mock_session(found=row)
    result = await get_or_404(session, _Widget, "w1", entity="widget")
    assert result is row
    session.execute.assert_awaited_once()


async def test_get_or_404_raises_when_missing() -> None:
    session = _mock_session(found=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_or_404(session, _Widget, "missing", entity="widget")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "widget not found"


async def test_get_or_404_detail_uses_provided_entity_label() -> None:
    session = _mock_session(found=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_or_404(session, _Widget, "missing", entity="custom order")
    assert exc_info.value.detail == "custom order not found"
