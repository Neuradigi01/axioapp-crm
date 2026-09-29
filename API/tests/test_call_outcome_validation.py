"""Call-outcome admin rules: payload validation + unique names (Settings → Call Outcomes)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.app.core.calls.schemas import CallOutcomeCreate, CallOutcomeUpdate
from src.app.core.calls.service import _ensure_label_unique


def test_create_payload_is_normalised() -> None:
    payload = CallOutcomeCreate(
        key="call_back_later", label="  Call   back later ", color="#10B981"
    )
    assert payload.label == "Call back later"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", "   "),
        ("label", "x" * 129),
        ("color", "red"),
        ("color", "#12345"),
        ("key", "Call Back"),
        ("key", ""),
        ("display_order", -1),
    ],
)
def test_create_payload_rejects_bad_values(field: str, value: object) -> None:
    data: dict[str, object] = {"key": "interested", "label": "Interested", "color": "#10b981"}
    data[field] = value
    with pytest.raises(ValidationError):
        CallOutcomeCreate(**data)


def test_update_payload_rejects_blank_label_and_bad_colour() -> None:
    with pytest.raises(ValidationError):
        CallOutcomeUpdate(label="  ")
    with pytest.raises(ValidationError):
        CallOutcomeUpdate(color="blue")
    assert CallOutcomeUpdate(display_order=20).model_dump(exclude_unset=True) == {
        "display_order": 20
    }


def test_duplicate_label_is_case_insensitive() -> None:
    existing = [SimpleNamespace(id=uuid.uuid4(), label="Connected")]
    with pytest.raises(HTTPException) as exc:
        _ensure_label_unique(existing, "connected")
    assert exc.value.status_code == 409
    _ensure_label_unique(existing, "Interested")
