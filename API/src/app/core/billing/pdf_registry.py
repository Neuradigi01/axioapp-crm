"""Pluggable PDF renderer registry — keeps `core/billing` template-agnostic.

The pack registers a callable that takes the invoice + its lines and
returns `(bytes, filename)`. The core router calls the registered
renderer when a client requests `GET /invoices/{id}/pdf`. If no
renderer is registered, the endpoint returns 501 — that's a real
configuration error rather than a hidden default.

This is the same pattern the conversations channel registry uses
(adapters register at import time; core never imports the pack).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.app.core.billing.models import Invoice, InvoiceLine

# (Invoice, list[InvoiceLine], dict[str, str | None]) -> (bytes, filename)
RendererFn = Callable[
    [Invoice, list[InvoiceLine], dict[str, str | None]],
    Awaitable[tuple[bytes, str]],
]


_renderer: RendererFn | None = None


def register_renderer(fn: RendererFn) -> None:
    """Packs call this at import time."""
    global _renderer
    _renderer = fn


def get_renderer() -> RendererFn | None:
    return _renderer
