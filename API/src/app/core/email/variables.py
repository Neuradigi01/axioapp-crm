"""Backwards-compatible re-export shim.

This module's contents moved to :mod:`src.app.core.templates.variables`
in Step 2 of ``tasks/template-library/``. Every public symbol is
re-exported here so existing email-template callers keep working
unchanged.

Step 10 of the same track folds ``core/email_templates/`` into
``core/templates/`` and deletes this shim; until then the old import
paths continue to resolve.
"""
from src.app.core.templates.variables import (  # noqa: F401
    MissingVariable,
    TemplateSyntaxError,
    extract_variable_paths,
    reject_jinja_statements,
    render,
)


__all__ = [
    "MissingVariable",
    "TemplateSyntaxError",
    "extract_variable_paths",
    "reject_jinja_statements",
    "render",
]
