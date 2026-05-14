"""Furniture-pack: field-ops module.

Third Layer-2 (pack) module. Reuses the core appointments engine for
scheduling and the custom-orders module for measurement copyback.

No `register_pipeline_table` call — field visits don't carry a
pipeline_stage column; they transition through the standard
appointment status enum (scheduled → completed) plus a per-visit
`completed_at` timestamp.
"""
from src.app.packs.furniture.modules.field_ops.service import (
    add_photo,
    complete_visit,
    create_visit,
    delete_visit,
    get_visit,
    list_photos,
    list_visits,
    update_visit,
)


__all__ = [
    "add_photo",
    "complete_visit",
    "create_visit",
    "delete_visit",
    "get_visit",
    "list_photos",
    "list_visits",
    "update_visit",
]
