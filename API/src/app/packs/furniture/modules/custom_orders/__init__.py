"""Furniture-pack: custom-orders module.

Second Layer-2 (pack) module to touch the database. All tables are
`fp_*` prefixed.

Importing this module registers `fp_custom_orders` as a
pipeline-tracked card table with the core pipelines engine — that's
the allowlist `pipelines.move_card` consults before issuing a raw
UPDATE.
"""
from src.app.core.pipelines.service import register_pipeline_table
from src.app.packs.furniture.modules.custom_orders.service import (
    add_measurement,
    add_photo,
    create_order,
    delete_order,
    get_order,
    list_measurements,
    list_orders,
    list_photos,
    list_stage_history,
    move_stage,
    update_order,
)


register_pipeline_table("fp_custom_orders")


__all__ = [
    "add_measurement",
    "add_photo",
    "create_order",
    "delete_order",
    "get_order",
    "list_measurements",
    "list_orders",
    "list_photos",
    "list_stage_history",
    "move_stage",
    "update_order",
]
