"""Generic audit-snapshot builder.

Every service used to ship a hand-rolled ``_snapshot(entity) -> dict``
that returned a JSON-safe projection of an ORM row for the audit
``before`` / ``after`` payload. The logic was structurally identical
across modules — pick N attributes, coerce UUIDs/datetimes/Decimals/
Enums to JSON-friendly primitives, return a dict — so this module
extracts the coercion into one place.

:func:`snapshot` is the entry point. Callers still curate which
fields are audit-relevant via the ``fields`` whitelist — audit
payloads stay tight on purpose so dashboards aren't drowning in
``created_at`` / ``updated_at`` / ``org_id`` noise that the audit row
itself already carries.

Output dicts preserve insertion order matching the ``fields`` tuple,
so a migrated ``_snapshot()`` returns a payload bit-identical to the
hand-rolled version (provided ``fields`` lists keys in the original
order).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable


def _coerce(value: Any) -> Any:
    """Convert a SQLAlchemy column value to a JSON-safe primitive.

    Handles the five types the hand-rolled snapshots used to coerce
    manually:

    - ``None``                  passes through
    - ``uuid.UUID``             → ``str(value)``
    - ``datetime`` / ``date``   → ``value.isoformat()``
    - ``Decimal``               → ``str(value)`` (preserves precision)
    - ``Enum``                  → ``value.value``
    - ``list`` / ``tuple``      → recursively coerced ``list``
    - everything else           passes through unchanged (``int``,
      ``str``, ``bool``, JSONB ``dict``, …)
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    return value


def snapshot(entity: object, *, fields: Iterable[str]) -> dict[str, Any]:
    """Return a JSON-safe dict of ``entity``'s attributes named in ``fields``.

    Each name is looked up via :func:`getattr`; missing attributes raise
    ``AttributeError`` (loudly — better than a silently-wrong audit
    payload). Values are passed through :func:`_coerce` so the dict is
    safe to drop straight into Postgres JSONB.
    """
    return {name: _coerce(getattr(entity, name)) for name in fields}
