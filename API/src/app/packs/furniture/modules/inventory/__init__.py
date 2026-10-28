"""Furniture-pack: inventory + warehouse module.

First Layer-2 (pack) module to touch the database. All tables are
`fp_*` prefixed so platform tables and pack tables are clearly
separated in any DB dump.
"""

from src.app.packs.furniture.modules.inventory.service import (
    create_item,
    create_warehouse,
    list_alerts,
    list_items,
    list_movements,
    list_warehouses,
    recompute_alerts,
    record_movement,
)

__all__ = [
    "create_item",
    "create_warehouse",
    "list_alerts",
    "list_items",
    "list_movements",
    "list_warehouses",
    "record_movement",
    "recompute_alerts",
]
