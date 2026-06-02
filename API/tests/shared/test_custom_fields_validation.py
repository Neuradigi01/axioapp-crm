"""Unit tests for the shared `validate_custom_data` orchestrator.

The engine consolidates the `_load_field_defs` + per-type coercion +
required-fields check that used to be duplicated in five service
modules. Per-type coercion lives in
`src.app.shared.custom_fields.coercion` (covered separately by
``test_field_coercion``); this file pins the orchestration layer:
unknown-key rejection, required-field enforcement, and the bit-
identical 422 detail strings the FE dynamic-form renderer parses.

A mocked session is used so no live DB is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.app.core.custom_fields.models import FieldType
from src.app.shared.custom_fields import validate_custom_data


def _make_def(field_key: str, field_type: FieldType, *, is_required: bool = False):
    """Stand-in for a CustomFieldDefinition row — only the attributes
    the engine reads are populated."""
    return SimpleNamespace(
        field_key=field_key,
        field_type=field_type,
        is_required=is_required,
    )


def _mock_session(defs: list) -> MagicMock:
    """Mock AsyncSession.execute → result.scalars() → defs."""
    scalars = MagicMock()
    scalars.__iter__ = lambda self: iter(defs)
    result = MagicMock()
    result.scalars.return_value = scalars
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


# --- validate_custom_data -----------------------------------------------


async def test_validate_returns_cleaned_payload() -> None:
    session = _mock_session(
        [
            _make_def("color", FieldType.text),
            _make_def("budget", FieldType.number),
        ]
    )
    result = await validate_custom_data(
        session,
        entity_type="contact",
        payload={"color": "red", "budget": 50000},
        require_all_required=False,
    )
    assert result == {"color": "red", "budget": 50000}


async def test_validate_rejects_unknown_key_with_entity_in_message() -> None:
    """The 422 detail includes the entity name verbatim — the FE form
    renderer parses this to highlight the bad field."""
    session = _mock_session([_make_def("color", FieldType.text)])
    with pytest.raises(HTTPException) as exc:
        await validate_custom_data(
            session,
            entity_type="lead",
            payload={"unknown_key": "x"},
            require_all_required=False,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == (
        "custom_data contains keys not defined for entity 'lead': ['unknown_key']"
    )


async def test_validate_enforces_required_on_create() -> None:
    session = _mock_session(
        [
            _make_def("color", FieldType.text, is_required=True),
            _make_def("note", FieldType.text),
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await validate_custom_data(
            session,
            entity_type="contact",
            payload={"note": "hi"},
            require_all_required=True,
        )
    assert exc.value.detail == "custom_data missing required keys: ['color']"


async def test_validate_skips_required_check_on_update() -> None:
    """`require_all_required=False` is the partial-update mode — missing
    required keys are NOT an error then."""
    session = _mock_session(
        [_make_def("color", FieldType.text, is_required=True)]
    )
    result = await validate_custom_data(
        session,
        entity_type="contact",
        payload={},
        require_all_required=False,
    )
    assert result == {}


async def test_validate_propagates_per_value_error() -> None:
    """Type mismatches surface as per-key 422s with the same format as
    the per-entity validators used to emit."""
    session = _mock_session([_make_def("budget", FieldType.number)])
    with pytest.raises(HTTPException) as exc:
        await validate_custom_data(
            session,
            entity_type="lead",
            payload={"budget": "not-a-number"},
            require_all_required=False,
        )
    assert exc.value.detail == "custom_data.budget: expected number"


async def test_validate_treats_explicit_none_as_missing_for_required() -> None:
    """If a required field is present with value=None, it still counts
    as missing (matches pre-refactor `key not in cleaned or cleaned[key] is None`)."""
    session = _mock_session(
        [_make_def("color", FieldType.text, is_required=True)]
    )
    with pytest.raises(HTTPException) as exc:
        await validate_custom_data(
            session,
            entity_type="contact",
            payload={"color": None},
            require_all_required=True,
        )
    assert exc.value.detail == "custom_data missing required keys: ['color']"


async def test_validate_entity_type_appears_in_db_query() -> None:
    """Helper passes the caller's entity_type into the load query."""
    session = _mock_session([])
    await validate_custom_data(
        session,
        entity_type="walk_in",
        payload={},
        require_all_required=False,
    )
    # The compiled SELECT should mention "walk_in" in its bind params.
    issued_stmt = session.execute.await_args.args[0]
    compiled = issued_stmt.compile(compile_kwargs={"literal_binds": True})
    assert "walk_in" in str(compiled)
