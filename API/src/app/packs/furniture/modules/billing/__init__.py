"""Furniture-pack: Billing & POS module.

Importing this package registers a furniture-themed invoice PDF
renderer with the core billing engine. The core router uses that
renderer when a client requests `GET /api/v1/invoices/{id}/pdf` —
core has no hard dependency on it.
"""
from src.app.core.billing.pdf_registry import register_renderer
from src.app.packs.furniture.modules.billing.pdf import render_invoice_pdf


register_renderer(render_invoice_pdf)


__all__ = ["render_invoice_pdf"]
