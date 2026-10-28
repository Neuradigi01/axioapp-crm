"""Unit tests for the shared `TimestampedOrgScopedOut` mixin.

Confirms the three fields every tenant-scoped output schema used to
redeclare (`org_id`, `created_at`, `updated_at`) are inherited
correctly and that ``model_validate(orm_row)`` still works for
subclasses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut


def test_mixin_declares_expected_fields() -> None:
    assert list(TimestampedOrgScopedOut.model_fields.keys()) == [
        "org_id",
        "created_at",
        "updated_at",
    ]


def test_mixin_inherits_orm_config() -> None:
    """`from_attributes=True` + `populate_by_name=True` propagate down
    from `ORMModel`, so subclasses can `model_validate` an ORM row."""

    assert issubclass(TimestampedOrgScopedOut, ORMModel)
    assert TimestampedOrgScopedOut.model_config["from_attributes"] is True


def test_subclass_inherits_three_fields_then_appends_its_own() -> None:
    """A subclass declares only its own extra fields. Pydantic v2 puts
    inherited fields first — the JSON ordering shifts but every key is
    still accessible by name."""

    class _ContactOut(TimestampedOrgScopedOut):
        id: uuid.UUID
        name: str

    assert list(_ContactOut.model_fields.keys()) == [
        "org_id",
        "created_at",
        "updated_at",
        "id",
        "name",
    ]


def test_model_validate_from_attribute_row() -> None:
    """Mirrors the router-side pattern: build the schema from a
    SQLAlchemy-row-like object via ``model_validate(row)``."""

    class _Row:
        org_id = uuid.uuid4()
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        updated_at = datetime(2026, 6, 1, tzinfo=UTC)
        id = uuid.uuid4()
        name = "alpha"

    class _ContactOut(TimestampedOrgScopedOut):
        id: uuid.UUID
        name: str

    row = _Row()
    result = _ContactOut.model_validate(row)
    assert result.org_id == row.org_id
    assert result.created_at == row.created_at
    assert result.updated_at == row.updated_at
    assert result.id == row.id
    assert result.name == "alpha"


def test_missing_org_id_raises() -> None:
    """`org_id` is required (rule 2): omission must surface as a 422-
    flavoured ValidationError, not silently default to None."""

    class _Out(TimestampedOrgScopedOut):
        id: uuid.UUID

    with pytest.raises(ValidationError) as exc_info:
        _Out.model_validate(
            {
                "id": uuid.uuid4(),
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                # org_id missing
            }
        )
    assert any(
        err["loc"] == ("org_id",) and err["type"] == "missing" for err in exc_info.value.errors()
    )
