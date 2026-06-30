"""Per-type coercers for ``custom_data`` JSONB values.

Each ``FieldType`` is handled by a small dedicated function; the
``_COERCERS`` dispatch table maps types → coercers and is the single
source of truth for "which function validates which type". Adding a
new field type is a two-line change: add the coercer below, add it to
the table.

The 422 message format (``custom_data.<key>: <what was wrong>``) is
preserved bit-identically with the pre-refactor inlined switches so
the FE dynamic-form renderer keeps parsing them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as _date
from datetime import datetime as _datetime
from typing import Any

from fastapi import HTTPException, status

from src.app.core.custom_fields.models import FieldType


def _bad(key: str, msg: str) -> HTTPException:
    """Build the canonical per-key 422 for a coercion failure."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"custom_data.{key}: {msg}",
    )


# --- Per-type coercers ----------------------------------------------------


def coerce_string(key: str, value: Any) -> str:
    """text / phone / email / select all share this — they're free strings
    at the JSON layer. The FE form does user-facing format validation
    (e.g. email regex, phone E.164); this layer only enforces the type."""
    if not isinstance(value, str):
        raise _bad(key, "expected string")
    return value


def coerce_string_list(key: str, value: Any) -> list[str]:
    """multiselect — list whose every element is a string."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad(key, "expected list of strings")
    return value


def coerce_number(key: str, value: Any) -> int | float:
    """number / currency. ``bool`` is an ``int`` subclass in Python —
    rejected explicitly so ``True`` doesn't sneak past."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(key, "expected number")
    return value


def coerce_boolean(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise _bad(key, "expected boolean")
    return value


def coerce_iso_date(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise _bad(key, "expected ISO date string")
    try:
        _date.fromisoformat(value)
    except ValueError as exc:
        raise _bad(key, "invalid ISO date") from exc
    return value


def coerce_iso_datetime(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise _bad(key, "expected ISO datetime string")
    try:
        _datetime.fromisoformat(value)
    except ValueError as exc:
        raise _bad(key, "invalid ISO datetime") from exc
    return value


# --- Dispatch -------------------------------------------------------------


_COERCERS: dict[FieldType, Callable[[str, Any], Any]] = {
    FieldType.text: coerce_string,
    FieldType.phone: coerce_string,
    FieldType.email: coerce_string,
    FieldType.select: coerce_string,
    FieldType.multiselect: coerce_string_list,
    FieldType.number: coerce_number,
    FieldType.currency: coerce_number,
    FieldType.boolean: coerce_boolean,
    FieldType.date: coerce_iso_date,
    FieldType.datetime: coerce_iso_datetime,
}


def coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    """Validate / coerce a single ``custom_data`` value.

    ``None`` passes through (used for cleared optional fields). Any
    other value is dispatched to the coercer registered for
    ``field_type``. Raises 422 on per-type mismatch. Raises 500 if a
    new ``FieldType`` is added to the enum without being registered
    here — fail loudly over silently accepting whatever the caller sent.
    """
    if value is None:
        return None
    coercer = _COERCERS.get(field_type)
    if coercer is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unhandled field_type {field_type!r}",
        )
    return coercer(key, value)
