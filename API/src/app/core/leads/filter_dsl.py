"""Lead filter DSL — JSON-in, SQLAlchemy-clauses-out (+ in-memory eval).

Used by:

  - ``list_leads`` and the CSV export endpoint: SQL via ``to_sqlalchemy``.
  - The scoring engine: in-memory via ``matches`` (one lead at a time,
    no DB round-trip per rule).

Shape::

    {
      "all": [<clause>, ...],   # AND group (optional)
      "any": [<clause>, ...]    # OR  group (optional)
    }

Clause::

    {"field": "<field>", "op": "<op>", "value": <any>}

Hard limits (cheap DoS guardrails):

  - Max 20 clauses across ``all`` + ``any``.
  - Max depth 1 (no nested groups in v1).
  - Custom-field keys ≤ 64 chars and must be present in
    ``custom_field_definitions`` for the org (checked by the caller
    passing ``allowed_custom_keys`` to ``to_sqlalchemy``).

Two field categories:

  - **Lead-direct**: live on the ``leads`` row, evaluable in-memory.
    The scoring engine accepts only these via ``validate_scorable``.
  - **Contact-joined**: ``contact_name`` / ``contact_phone`` /
    ``contact_email`` — require the ``contacts`` JOIN. SQL builder
    handles them; the in-memory evaluator raises if asked, which is
    why scoring rules can't reference them.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead

# --- whitelist tables -------------------------------------------------------

LEAD_DIRECT_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "source",
        "assigned_to_id",
        "lead_score",
        "budget",
        "last_activity_at",
        "created_at",
        "expected_close_date",
        "pipeline_stage",
    }
)

CONTACT_JOINED_FIELDS: frozenset[str] = frozenset(
    {
        "contact_name",
        "contact_phone",
        "contact_email",
    }
)

ALL_FIELDS: frozenset[str] = LEAD_DIRECT_FIELDS | CONTACT_JOINED_FIELDS

OPS: frozenset[str] = frozenset(
    {
        "eq",
        "neq",
        "in",
        "nin",
        "gt",
        "gte",
        "lt",
        "lte",
        "contains",
        "starts_with",
        "between",
        "is_empty",
        "is_not_empty",
    }
)

# Ops that don't need a `value` (the field is being tested for null).
_VALUELESS_OPS: frozenset[str] = frozenset({"is_empty", "is_not_empty"})

# Per-field type hint, used by ``_coerce_scalar`` to coerce JSON-numeric
# input ("50000" or 50000) into the right Python type before the SQL
# builder hands it to SQLAlchemy. Custom_data values are always astext
# strings — coerce them as ``str`` so ``ilike`` etc. work consistently.
_FIELD_PY_TYPE: dict[str, str] = {
    "status": "str",
    "source": "str",
    "assigned_to_id": "uuid",
    "lead_score": "int",
    "budget": "decimal",
    "last_activity_at": "datetime",
    "created_at": "datetime",
    "expected_close_date": "date",
    "pipeline_stage": "str",
    "contact_name": "str",
    "contact_phone": "str",
    "contact_email": "str",
}

_CUSTOM_PREFIX = "custom_data."
_MAX_CUSTOM_KEY_LEN = 64
MAX_CLAUSES = 20


# --- dataclasses ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Clause:
    field: str
    op: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class Filter:
    """Parsed DSL — two flat clause lists. Empty filter matches everything."""

    all_: list[Clause] = field(default_factory=list)
    any_: list[Clause] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.all_ and not self.any_


class FilterDslError(ValueError):
    """Raised on any DSL parsing / validation problem. Caller maps to 422."""


# --- public surface ---------------------------------------------------------


def parse(dsl: Any) -> Filter:
    """Validate the JSON shape and return a ``Filter``.

    Accepts ``None`` / ``{}`` → empty filter (matches everything). Any
    structural problem raises ``FilterDslError``.
    """
    if dsl is None:
        return Filter()
    if not isinstance(dsl, dict):
        raise FilterDslError("filter must be a JSON object")

    extra_keys = set(dsl) - {"all", "any"}
    if extra_keys:
        raise FilterDslError(f"filter has unsupported top-level keys: {sorted(extra_keys)}")

    all_clauses = _parse_clause_list(dsl.get("all"), group="all")
    any_clauses = _parse_clause_list(dsl.get("any"), group="any")

    total = len(all_clauses) + len(any_clauses)
    if total > MAX_CLAUSES:
        raise FilterDslError(f"filter has {total} clauses; max is {MAX_CLAUSES}")

    return Filter(all_=all_clauses, any_=any_clauses)


def to_sqlalchemy(
    filter_: Filter,
    *,
    allowed_custom_keys: set[str] | None = None,
) -> tuple[ColumnElement | None, bool]:
    """Compile a parsed ``Filter`` into a single boolean SQL clause.

    Returns ``(clause_or_None, needs_contact_join)``. An empty filter
    returns ``(None, False)``. The caller is responsible for adding the
    JOIN when ``needs_contact_join`` is True.
    """
    if filter_.is_empty():
        return None, False

    needs_join = False
    pieces: list[ColumnElement] = []

    if filter_.all_:
        sub: list[ColumnElement] = []
        for clause in filter_.all_:
            expr, j = _clause_to_sql(clause, allowed_custom_keys)
            sub.append(expr)
            needs_join = needs_join or j
        pieces.append(and_(*sub))

    if filter_.any_:
        sub = []
        for clause in filter_.any_:
            expr, j = _clause_to_sql(clause, allowed_custom_keys)
            sub.append(expr)
            needs_join = needs_join or j
        pieces.append(or_(*sub))

    combined = pieces[0] if len(pieces) == 1 else and_(*pieces)
    return combined, needs_join


def matches(filter_: Filter, *, lead: Lead) -> bool:
    """Evaluate ``filter_`` against a single ``Lead`` in memory.

    Used by the scoring engine. Raises ``FilterDslError`` if any clause
    references a contact-joined field — scoring rules can't reference
    those (enforced at rule-create time by ``validate_scorable``).
    """
    if filter_.is_empty():
        return True

    if filter_.all_ and not all(_clause_matches(c, lead) for c in filter_.all_):
        return False
    if filter_.any_ and not any(_clause_matches(c, lead) for c in filter_.any_):
        return False
    return True


def validate_scorable(filter_: Filter) -> None:
    """Reject filters that reference contact-joined fields.

    Scoring rules must be evaluable in-memory because the engine runs
    one lead at a time without a contact JOIN. Raises ``FilterDslError``
    on violation.
    """
    for clause in (*filter_.all_, *filter_.any_):
        if clause.field in CONTACT_JOINED_FIELDS:
            raise FilterDslError(
                f"scoring rules cannot reference contact-joined field "
                f"{clause.field!r}; use a lead-direct field instead"
            )


def fields_referenced(filter_: Filter) -> set[str]:
    """Set of field names this filter touches. Used by the scoring
    engine to decide whether a lead update needs a recompute."""
    return {c.field for c in (*filter_.all_, *filter_.any_)}


# --- internals --------------------------------------------------------------


def _parse_clause_list(raw: Any, *, group: str) -> list[Clause]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FilterDslError(f"filter.{group} must be a list of clauses")
    return [_parse_clause(c, group=group, index=i) for i, c in enumerate(raw)]


def _parse_clause(raw: Any, *, group: str, index: int) -> Clause:
    where = f"filter.{group}[{index}]"
    if not isinstance(raw, dict):
        raise FilterDslError(f"{where} must be an object")
    extra = set(raw) - {"field", "op", "value"}
    if extra:
        raise FilterDslError(f"{where} has unsupported keys: {sorted(extra)}")

    field_ = raw.get("field")
    op = raw.get("op")
    if not isinstance(field_, str) or not field_:
        raise FilterDslError(f"{where}.field is required and must be a string")
    if not isinstance(op, str) or op not in OPS:
        raise FilterDslError(f"{where}.op {op!r} is not one of {sorted(OPS)}")

    if field_.startswith(_CUSTOM_PREFIX):
        key = field_[len(_CUSTOM_PREFIX) :]
        if not key or len(key) > _MAX_CUSTOM_KEY_LEN:
            raise FilterDslError(f"{where}.field has an invalid custom_data key {key!r}")
        # Key existence in custom_field_definitions is checked later by
        # the SQL builder (it needs the per-org set).
    elif field_ not in ALL_FIELDS:
        raise FilterDslError(f"{where}.field {field_!r} is not a recognised lead field")

    value = raw.get("value")
    if op in _VALUELESS_OPS:
        if value is not None:
            raise FilterDslError(f"{where}: op {op!r} must not carry a value")
    else:
        if "value" not in raw:
            raise FilterDslError(f"{where}: op {op!r} requires a 'value' key")

    return Clause(field=field_, op=op, value=value)


def _clause_to_sql(
    clause: Clause,
    allowed_custom_keys: set[str] | None,
) -> tuple[ColumnElement, bool]:
    """Compile one clause → SQL boolean expression. Returns
    ``(expr, needs_contact_join)``."""
    col, is_contact, py_type = _resolve_column(clause.field, allowed_custom_keys)

    if clause.op == "is_empty":
        return col.is_(None), is_contact
    if clause.op == "is_not_empty":
        return col.isnot(None), is_contact

    if clause.op in ("in", "nin"):
        values = _coerce_sequence(clause.value, py_type, clause.field)
        expr = col.in_(values) if clause.op == "in" else col.notin_(values)
        return expr, is_contact

    if clause.op == "between":
        values = _coerce_sequence(clause.value, py_type, clause.field)
        if len(values) != 2:
            raise FilterDslError(f"clause {clause.field}: 'between' needs a 2-element list")
        lo, hi = values
        return col.between(lo, hi), is_contact

    scalar = _coerce_scalar(clause.value, py_type, clause.field)

    if clause.op == "eq":
        return col == scalar, is_contact
    if clause.op == "neq":
        return col != scalar, is_contact
    if clause.op == "gt":
        return col > scalar, is_contact
    if clause.op == "gte":
        return col >= scalar, is_contact
    if clause.op == "lt":
        return col < scalar, is_contact
    if clause.op == "lte":
        return col <= scalar, is_contact
    if clause.op == "contains":
        if not isinstance(scalar, str):
            raise FilterDslError(f"clause {clause.field}: 'contains' needs a string value")
        return col.ilike(f"%{scalar}%"), is_contact
    if clause.op == "starts_with":
        if not isinstance(scalar, str):
            raise FilterDslError(f"clause {clause.field}: 'starts_with' needs a string value")
        return col.ilike(f"{scalar}%"), is_contact

    # Unreachable: parser already rejected unknown ops.
    raise FilterDslError(f"unhandled op {clause.op!r}")


def _resolve_column(
    field_name: str,
    allowed_custom_keys: set[str] | None,
) -> tuple[Any, bool, str]:
    """Resolve a DSL field name to a SQLAlchemy column expression.

    Returns ``(column, is_contact_joined, py_type)``.
    """
    if field_name.startswith(_CUSTOM_PREFIX):
        key = field_name[len(_CUSTOM_PREFIX) :]
        if allowed_custom_keys is not None and key not in allowed_custom_keys:
            raise FilterDslError(f"custom_data.{key!r} is not a defined custom field for this org")
        return Lead.custom_data[key].astext, False, "str"

    if field_name == "contact_name":
        return Contact.full_name, True, "str"
    if field_name == "contact_phone":
        return Contact.phone, True, "str"
    if field_name == "contact_email":
        return Contact.email, True, "str"

    # Lead-direct
    column = getattr(Lead, field_name)
    return column, False, _FIELD_PY_TYPE[field_name]


def _coerce_scalar(value: Any, py_type: str, field_name: str) -> Any:
    """Coerce a JSON-decoded value into the Python type the column expects."""
    if value is None:
        raise FilterDslError(f"clause {field_name}: value cannot be null (use is_empty)")
    try:
        if py_type == "str":
            if not isinstance(value, (str, int, float)):
                raise FilterDslError(
                    f"clause {field_name}: expected string, got {type(value).__name__}"
                )
            return str(value)
        if py_type == "int":
            if isinstance(value, bool):
                raise FilterDslError(f"clause {field_name}: expected int, got bool")
            return int(value)
        if py_type == "decimal":
            return Decimal(str(value))
        if py_type == "uuid":
            return uuid.UUID(str(value))
        if py_type == "datetime":
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))
        if py_type == "date":
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            return date.fromisoformat(str(value))
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise FilterDslError(
            f"clause {field_name}: invalid value {value!r} for type {py_type}"
        ) from exc
    raise FilterDslError(f"unhandled py_type {py_type!r}")


def _coerce_sequence(value: Any, py_type: str, field_name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise FilterDslError(f"clause {field_name}: expected a list of values")
    if not value:
        raise FilterDslError(f"clause {field_name}: value list cannot be empty")
    return [_coerce_scalar(v, py_type, field_name) for v in value]


# --- in-memory evaluation ---------------------------------------------------


def _clause_matches(clause: Clause, lead: Lead) -> bool:
    if clause.field in CONTACT_JOINED_FIELDS:
        raise FilterDslError(
            f"in-memory eval does not support contact-joined field {clause.field!r}"
        )

    if clause.field.startswith(_CUSTOM_PREFIX):
        key = clause.field[len(_CUSTOM_PREFIX) :]
        lead_value: Any = (lead.custom_data or {}).get(key)
        py_type = "str"
    else:
        lead_value = getattr(lead, clause.field, None)
        py_type = _FIELD_PY_TYPE[clause.field]

    # Unwrap enum values so equality with scalar string DSL inputs works.
    # ``LeadStatus(str, Enum)`` is str-subclassed but ``str(LeadStatus.active)``
    # returns ``"LeadStatus.active"`` — we want ``"active"``.
    if isinstance(lead_value, enum.Enum):
        lead_value = lead_value.value

    op = clause.op
    if op == "is_empty":
        return lead_value in (None, "", [], {})
    if op == "is_not_empty":
        return lead_value not in (None, "", [], {})

    if op in ("in", "nin"):
        values = _coerce_sequence(clause.value, py_type, clause.field)
        present = _normalise_for_compare(lead_value, py_type) in values
        return present if op == "in" else not present

    if op == "between":
        values = _coerce_sequence(clause.value, py_type, clause.field)
        if len(values) != 2:
            raise FilterDslError(f"clause {clause.field}: 'between' needs a 2-element list")
        lo, hi = values
        return _between(lead_value, lo, hi)

    scalar = _coerce_scalar(clause.value, py_type, clause.field)
    normed = _normalise_for_compare(lead_value, py_type)

    if op == "eq":
        return normed == scalar
    if op == "neq":
        return normed != scalar
    if op in ("gt", "gte", "lt", "lte"):
        if normed is None:
            return False
        if op == "gt":
            return normed > scalar
        if op == "gte":
            return normed >= scalar
        if op == "lt":
            return normed < scalar
        return normed <= scalar  # lte
    if op == "contains":
        if not isinstance(normed, str) or not isinstance(scalar, str):
            return False
        return scalar.lower() in normed.lower()
    if op == "starts_with":
        if not isinstance(normed, str) or not isinstance(scalar, str):
            return False
        return normed.lower().startswith(scalar.lower())

    raise FilterDslError(f"unhandled op {op!r}")


def _normalise_for_compare(value: Any, py_type: str) -> Any:
    """Make a lead-attribute value comparable to a coerced DSL scalar."""
    if value is None:
        return None
    try:
        if py_type == "str":
            return str(value)
        if py_type == "int":
            return int(value)
        if py_type == "decimal":
            return Decimal(str(value))
        if py_type == "uuid":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if py_type == "datetime":
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if py_type == "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (ValueError, InvalidOperation, TypeError):
        return None
    return value


def _between(value: Any, lo: Any, hi: Any) -> bool:
    if value is None:
        return False
    try:
        return lo <= value <= hi
    except TypeError:
        return False


__all__ = [
    "ALL_FIELDS",
    "CONTACT_JOINED_FIELDS",
    "Clause",
    "Filter",
    "FilterDslError",
    "LEAD_DIRECT_FIELDS",
    "MAX_CLAUSES",
    "OPS",
    "fields_referenced",
    "matches",
    "parse",
    "to_sqlalchemy",
    "validate_scorable",
]
