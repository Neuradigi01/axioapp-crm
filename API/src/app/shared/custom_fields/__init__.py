"""Shared utilities for the per-org `custom_field_definitions` system.

The contents are organised so a vertical pack can add new ``FieldType``
values, register pack-specific defaults via the pack manifest, and
still use the same validation engine here for the actual write path.

Currently this module exposes the single public helper
:func:`validate_custom_data`. The lower-level coercion / field-loading
helpers are intentionally private — callers should compose at the
``validate_custom_data`` level so error-message formats stay uniform
across every entity.
"""

from src.app.shared.custom_fields.validation import validate_custom_data

__all__ = ["validate_custom_data"]
