"""Data-access layer for the WhatsApp integration module.

Per-module ``data_access/`` folder per the project convention. Pure
query helpers, no transactions, no audit. Leaf — never imports a
service.py.

Sub-modules:

  - :mod:`templates` — lookups against ``tbl_whatsapp_templates``
    including the Step-9 ``message_template_id`` reverse-lookup
    that lets a central template find its Meta-specific extension
    row.
"""
from src.app.core.integrations.whatsapp.data_access.templates import (
    get_by_id,
    get_by_message_template_id,
    get_by_meta_template_id,
)


__all__ = [
    "get_by_id",
    "get_by_message_template_id",
    "get_by_meta_template_id",
]
