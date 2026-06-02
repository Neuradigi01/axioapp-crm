"""Base Pydantic models shared across `app.core` and `app.packs`.

`ORMModel` is the parent class for every response/output schema that
materialises from a SQLAlchemy row. It pre-configures the two flags
every output schema used to repeat:

- ``from_attributes=True`` — ``model_validate(orm_row)`` reads
  attributes off the row instead of expecting a dict.
- ``populate_by_name=True`` — fields can be populated by alias **or**
  python name. Matches the one explicit use site (``users/schemas.py``)
  and is a forward-compatible default that doesn't break anything
  currently relying on plain ``from_attributes=True``.

Request/input schemas continue to inherit ``BaseModel`` directly —
they don't need attribute access and may declare their own
``ConfigDict(str_strip_whitespace=True)`` / ``extra="forbid"`` etc.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
