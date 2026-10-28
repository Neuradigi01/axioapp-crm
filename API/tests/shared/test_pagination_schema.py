"""Unit tests for the shared `PaginatedResponse[T]` envelope.

Pure Pydantic — no database required. These verify that the generic
behaves the same way as the hand-rolled `*ListResponse` classes it
replaces, so consumers (router constructors, frontend parsers) see
no behavioural change.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from src.app.shared.schemas import PaginatedResponse


class _Item(BaseModel):
    id: int
    name: str


def test_constructs_with_items_total_page_size() -> None:
    response = PaginatedResponse[_Item](
        items=[_Item(id=1, name="a"), _Item(id=2, name="b")],
        total=2,
        page=1,
        size=50,
    )
    assert response.total == 2
    assert response.page == 1
    assert response.size == 50
    assert [item.name for item in response.items] == ["a", "b"]


def test_serialises_to_expected_json_shape() -> None:
    response = PaginatedResponse[_Item](
        items=[_Item(id=1, name="a")],
        total=1,
        page=1,
        size=25,
    )
    payload = json.loads(response.model_dump_json())
    assert payload == {
        "items": [{"id": 1, "name": "a"}],
        "total": 1,
        "page": 1,
        "size": 25,
    }


def test_empty_page_is_valid() -> None:
    response = PaginatedResponse[_Item](items=[], total=0, page=1, size=50)
    assert response.items == []
    assert response.total == 0


def test_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        PaginatedResponse[_Item](items=[], total=0, page=1)  # type: ignore[call-arg]


def test_item_validation_rejects_wrong_shape() -> None:
    with pytest.raises(ValidationError):
        PaginatedResponse[_Item](
            items=[{"id": "not-an-int", "name": "x"}],  # type: ignore[list-item]
            total=1,
            page=1,
            size=50,
        )


def test_consumer_alias_constructs_same_instance() -> None:
    """Confirm a downstream alias (the pattern every migrated module
    uses) instantiates correctly and reports the right concrete type."""
    ItemListResponse = PaginatedResponse[_Item]
    response = ItemListResponse(items=[_Item(id=1, name="a")], total=1, page=1, size=50)
    assert isinstance(response, PaginatedResponse)
    assert response.items[0].name == "a"
