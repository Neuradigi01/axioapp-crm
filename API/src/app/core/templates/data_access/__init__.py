"""Data-access layer for the central template library.

Per-module ``data_access/`` folder per the project convention
(``feedback_data_access_naming.md``): pure query helpers, no
transactions, no audit, no commits. Leaf package — never imports a
``service.py``.

Sub-modules:

  - :mod:`templates` — lookups + filterable list against
    ``tbl_message_templates``.
  - :mod:`versions` — lookups against ``tbl_message_template_versions``.

``__init__`` re-exports the union so callers see a single
``data_access.X`` namespace.
"""
from src.app.core.templates.data_access.templates import (
    get_template,
    list_templates,
)
from src.app.core.templates.data_access.versions import (
    get_version,
    list_versions,
)


__all__ = [
    "get_template",
    "get_version",
    "list_templates",
    "list_versions",
]
