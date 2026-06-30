"""Core billing engine — invoices + payments.

The state machine lives in `service.py`; routes in `router.py`. The
PDF surface uses a registry (`pdf_registry`) so verticals can plug in
their own template without `core/` importing from `packs/`.
"""

from src.app.core.billing.service import (
    add_line,
    create_draft,
    get_invoice,
    get_invoice_with_lines,
    issue,
    list_invoices,
    list_payments,
    record_payment,
    remove_line,
    update_invoice,
    void,
)

__all__ = [
    "add_line",
    "create_draft",
    "get_invoice",
    "get_invoice_with_lines",
    "issue",
    "list_invoices",
    "list_payments",
    "record_payment",
    "remove_line",
    "update_invoice",
    "void",
]
