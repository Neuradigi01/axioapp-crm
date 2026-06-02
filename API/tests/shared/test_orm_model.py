"""Unit tests for the shared `ORMModel` base.

Confirms the two flags that every migrated output schema relies on:

- ``from_attributes=True`` — ``model_validate(obj)`` reads attributes
  off the object instead of expecting a dict (the SQLAlchemy-row case).
- ``populate_by_name=True`` — fields can be populated by either alias
  or python name (preserves the single explicit use site in
  ``users/schemas.py``).
"""

from __future__ import annotations

import pytest
from pydantic import Field, ValidationError

from src.app.shared.schemas import ORMModel


def test_model_validate_reads_attributes() -> None:
    """The from_attributes flag is what makes router code like
    `ContactOut.model_validate(contact_row)` work."""

    class _AttrRow:
        id = 7
        name = "alpha"

    class _Out(ORMModel):
        id: int
        name: str

    result = _Out.model_validate(_AttrRow())
    assert result.id == 7
    assert result.name == "alpha"


def test_model_validate_still_accepts_dict() -> None:
    class _Out(ORMModel):
        id: int
        name: str

    result = _Out.model_validate({"id": 1, "name": "beta"})
    assert result.id == 1
    assert result.name == "beta"


def test_populate_by_name_alias() -> None:
    """Mirrors UserOut: `id` has a `validation_alias` pointing at a
    different attribute. With populate_by_name=True a caller can still
    pass the python name explicitly."""

    class _Out(ORMModel):
        id: int = Field(validation_alias="legacy_id")

    by_alias = _Out.model_validate({"legacy_id": 42})
    by_python_name = _Out.model_validate({"id": 99})
    assert by_alias.id == 42
    assert by_python_name.id == 99


def test_validation_error_on_wrong_type() -> None:
    class _Out(ORMModel):
        id: int

    with pytest.raises(ValidationError):
        _Out.model_validate({"id": "not-an-int"})


def test_subclass_inherits_config() -> None:
    """`ORMModel`'s ConfigDict propagates to subclasses without each
    of them re-declaring it — the whole point of this refactor."""

    class _Row:
        id = 5

    class _Parent(ORMModel):
        id: int

    class _Child(_Parent):
        pass

    assert _Child.model_validate(_Row()).id == 5
