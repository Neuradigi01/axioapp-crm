"""Catalog module — bare-minimum product lookup for the universal CRM.

Re-exports service entry points (no FastAPI / Pydantic) so other
modules can `from src.app.core.catalog import get_item, list_items`
without dragging in HTTP-layer deps. The Phase 4 furniture pack
extends this with `fp_inventory_items` (multi-location, stock,
images) — but the universal `catalog_items` table stays the
authoritative "product interest" lookup core modules reference.
"""
from src.app.core.catalog.service import (
    create_item,
    delete_item,
    get_item,
    list_items,
    update_item,
)

__all__ = [
    "create_item",
    "delete_item",
    "get_item",
    "list_items",
    "update_item",
]
