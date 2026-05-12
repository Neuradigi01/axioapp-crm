"""Pipelines engine — generic kanban primitive for any entity that has
a `pipeline_stage` column.

Re-exports the service entry points (no FastAPI / Pydantic) so other
modules can `from src.app.core.pipelines import move_card,
register_pipeline_table` and wire their tables into the engine without
pulling in HTTP-layer deps.
"""
from src.app.core.pipelines.service import (
    get_pipeline_by_id,
    get_pipeline_by_key,
    get_stage,
    list_pipelines,
    move_card,
    register_pipeline_table,
    update_stage,
)

__all__ = [
    "get_pipeline_by_id",
    "get_pipeline_by_key",
    "get_stage",
    "list_pipelines",
    "move_card",
    "register_pipeline_table",
    "update_stage",
]
